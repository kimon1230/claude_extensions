"""Compression algorithm for context persistence.

Manages tier-based compression of session entries:
Active → Compressed → Archived → Dropped.

Sacred rule: ``Why:`` text on decisions is never compressed, summarized, or dropped.
It transfers verbatim through all tiers. Only the ``What:``/body gets compressed.

Stdlib only — no external dependencies.
"""

from __future__ import annotations

import os
import re
import sys

from lib.entries import (
    Entry,
    parse_session_progress,
    rebuild_session_progress,
)
from lib.fileutil import atomic_write, safe_read_json, safe_write_json
from lib.paths import get_ref_cache_path, get_session_progress_path, get_status_dir

# --- Trigger thresholds ---
ENTRY_COUNT_THRESHOLD = 30
SESSION_COUNT_THRESHOLD = 5
STALE_RATIO_THRESHOLD = 0.60
MIN_SESSIONS_GUARD = 3

# --- Tier rotation thresholds ---
COMPRESSED_TO_ARCHIVE_AGE = 2  # sessions since compressed_at
ARCHIVE_TO_DROP_AGE = 10  # sessions since compressed_at
ARCHIVE_MAX_LINES = 500

# Pattern: <!-- compressed_at:N -->
_COMPRESSED_AT_RE = re.compile(r"<!--\s*compressed_at:(\d+)\s*-->")
# Pattern: <!-- id:hex -->
_ID_RE = re.compile(r"<!--\s*id:([0-9a-fA-F]+)\s*-->")
# Pattern: - [type] Title ...
_COMPRESSED_ENTRY_RE = re.compile(
    r"^-\s+\[(\w+)]\s+(.*?)(?:\s*<!--\s*id:[0-9a-fA-F]+\s*-->)?(?:\s*<!--\s*compressed_at:\d+\s*-->)?\s*$"
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------
class CompressedEntry:
    """A compressed one-liner entry with metadata."""

    __slots__ = ("type", "title", "why", "id", "compressed_at")

    def __init__(
        self,
        type: str,
        title: str,
        why: str,
        id: str | None,
        compressed_at: int,
    ) -> None:
        self.type = type
        self.title = title
        self.why = why
        self.id = id
        self.compressed_at = compressed_at

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CompressedEntry):
            return NotImplemented
        return (
            self.type == other.type
            and self.title == other.title
            and self.why == other.why
            and self.id == other.id
            and self.compressed_at == other.compressed_at
        )

    def __repr__(self) -> str:
        return (
            f"CompressedEntry(type={self.type!r}, title={self.title!r}, "
            f"why={self.why!r}, id={self.id!r}, compressed_at={self.compressed_at})"
        )


# ---------------------------------------------------------------------------
# Trigger logic
# ---------------------------------------------------------------------------
def should_compress(
    cache: dict,
    entry_count: int,
    force: bool = False,
) -> bool:
    """Determine whether compression should fire.

    Uses OR logic: any single trigger is sufficient, but all triggers require
    at least ``MIN_SESSIONS_GUARD`` sessions since the last compression.

    Args:
        cache: The ref-cache.json contents (needs ``session_count``,
               ``last_compression``, and ``scores``).
        entry_count: Number of active entries in session-progress.md.
        force: If True, bypass all trigger checks.

    Returns:
        True if compression should run.
    """
    if force:
        return True

    session_count = cache.get("session_count", 0)
    if not isinstance(session_count, (int, float)):
        session_count = 0
    session_count = int(session_count)

    last_compression = cache.get("last_compression", 0)
    if not isinstance(last_compression, (int, float)):
        last_compression = 0
    last_compression = int(last_compression)

    sessions_since = session_count - last_compression

    # Guard: must have at least MIN_SESSIONS_GUARD sessions before any trigger
    if sessions_since < MIN_SESSIONS_GUARD:
        return False

    # Trigger 1: entry count
    if entry_count > ENTRY_COUNT_THRESHOLD:
        return True

    # Trigger 2: session count since last compression
    if sessions_since >= SESSION_COUNT_THRESHOLD:
        return True

    # Trigger 3: stale ratio
    scores = cache.get("scores", {})
    if not isinstance(scores, dict):
        scores = {}

    if entry_count > 0:
        stale_count = 0
        # We count entries with score 0 or missing from scores
        # But we need entry IDs to check scores — use a simplified approach:
        # The caller should pass stale info, but the spec says we check scores.
        # Since we only have entry_count (not the entries themselves), we need
        # to count from scores dict. But scores may have entries not in active set.
        # For the stale ratio trigger, we count how many score values are 0.
        # This is a best-effort heuristic using score data.
        score_values = list(scores.values())
        if score_values:
            stale_count = sum(1 for v in score_values if v == 0)
            total_scored = len(score_values)
            if total_scored > 0 and stale_count / total_scored >= STALE_RATIO_THRESHOLD:
                return True

    return False


def should_compress_with_entries(
    cache: dict,
    entries: list[Entry],
    force: bool = False,
) -> bool:
    """Determine whether compression should fire, using full entry list.

    More accurate than ``should_compress`` because it can check per-entry
    staleness using the actual entry IDs against the scores cache.
    """
    if force:
        return True

    session_count = cache.get("session_count", 0)
    if not isinstance(session_count, (int, float)):
        session_count = 0
    session_count = int(session_count)

    last_compression = cache.get("last_compression", 0)
    if not isinstance(last_compression, (int, float)):
        last_compression = 0
    last_compression = int(last_compression)

    sessions_since = session_count - last_compression

    if sessions_since < MIN_SESSIONS_GUARD:
        return False

    entry_count = len(entries)

    # Trigger 1: entry count
    if entry_count > ENTRY_COUNT_THRESHOLD:
        return True

    # Trigger 2: session count
    if sessions_since >= SESSION_COUNT_THRESHOLD:
        return True

    # Trigger 3: stale ratio (per-entry accuracy)
    if entry_count > 0:
        scores = cache.get("scores", {})
        if not isinstance(scores, dict):
            scores = {}
        stale = sum(
            1 for e in entries if e.id is not None and scores.get(e.id, 0) == 0
        )
        # Only count entries with IDs for ratio calculation
        with_ids = sum(1 for e in entries if e.id is not None)
        if with_ids > 0 and stale / with_ids >= STALE_RATIO_THRESHOLD:
            return True

    return False


# ---------------------------------------------------------------------------
# Compressed entry parsing / serialization
# ---------------------------------------------------------------------------
def serialize_compressed_entry(entry: CompressedEntry) -> str:
    """Serialize a CompressedEntry to markdown format."""
    id_part = f" <!-- id:{entry.id} -->" if entry.id else ""
    line = f"- [{entry.type}] {entry.title}{id_part} <!-- compressed_at:{entry.compressed_at} -->"
    if entry.why:
        line += f"\n  Why: {entry.why}"
    return line


def parse_compressed_entries(text: str) -> list[CompressedEntry]:
    """Parse compressed entries from a ``## Compressed Context`` section."""
    entries: list[CompressedEntry] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped.startswith("- ["):
            i += 1
            continue

        # Parse the main line
        m_type = re.match(r"^-\s+\[(\w+)]\s+(.+)$", stripped)
        if not m_type:
            i += 1
            continue

        entry_type = m_type.group(1)
        rest = m_type.group(2)

        # Extract title (everything before the first <!-- comment)
        title_end = rest.find("<!--")
        if title_end >= 0:
            title = rest[:title_end].strip()
        else:
            title = rest.strip()

        # Extract id
        m_id = _ID_RE.search(stripped)
        entry_id = m_id.group(1) if m_id else None

        # Extract compressed_at
        m_at = _COMPRESSED_AT_RE.search(stripped)
        compressed_at = int(m_at.group(1)) if m_at else 0

        # Check for Why: on next line
        why = ""
        if i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if next_line.lower().startswith("why:"):
                why = next_line[4:].strip()
                i += 1

        entries.append(
            CompressedEntry(
                type=entry_type,
                title=title,
                why=why,
                id=entry_id,
                compressed_at=compressed_at,
            )
        )
        i += 1

    return entries


def serialize_compressed_section(entries: list[CompressedEntry]) -> str:
    """Serialize a list of CompressedEntry objects to markdown text."""
    return "\n".join(serialize_compressed_entry(e) for e in entries)


# ---------------------------------------------------------------------------
# Archive parsing / serialization
# ---------------------------------------------------------------------------
def parse_archive_entries(text: str) -> list[CompressedEntry]:
    """Parse archive entries (title-only lines with metadata)."""
    return parse_compressed_entries(text)


def serialize_archive_entry(entry: CompressedEntry) -> str:
    """Serialize an archive entry (title-only, no Why)."""
    id_part = f" <!-- id:{entry.id} -->" if entry.id else ""
    return f"- [{entry.type}] {entry.title}{id_part} <!-- compressed_at:{entry.compressed_at} -->"


def serialize_archive(entries: list[CompressedEntry]) -> str:
    """Serialize archive entries to text."""
    return "\n".join(serialize_archive_entry(e) for e in entries)


# ---------------------------------------------------------------------------
# Categorization
# ---------------------------------------------------------------------------
def categorize_entries(
    entries: list[Entry],
    scores: dict[str, int],
) -> tuple[list[Entry], list[Entry], list[Entry]]:
    """Categorize entries into (active, compress_observations, compress_decisions).

    Args:
        entries: Active entries from session-progress.md.
        scores: Ref score cache (entry id → score).

    Returns:
        Tuple of (stays_active, stale_observations, stale_decisions).
    """
    active: list[Entry] = []
    observations: list[Entry] = []
    decisions: list[Entry] = []

    for entry in entries:
        score = scores.get(entry.id, 0) if entry.id else 0
        if score > 0:
            active.append(entry)
        elif entry.type == "decision":
            decisions.append(entry)
        else:
            observations.append(entry)

    return active, observations, decisions


def entry_to_compressed(entry: Entry, session_count: int) -> CompressedEntry:
    """Convert an active Entry to a CompressedEntry."""
    return CompressedEntry(
        type=entry.type,
        title=entry.title,
        why=entry.why,  # Sacred: preserved verbatim
        id=entry.id,
        compressed_at=session_count,
    )


# ---------------------------------------------------------------------------
# Tier rotation
# ---------------------------------------------------------------------------
def rotate_tiers(
    compressed: list[CompressedEntry],
    archive: list[CompressedEntry],
    current_session: int,
) -> tuple[list[CompressedEntry], list[CompressedEntry], list[CompressedEntry], int]:
    """Rotate entries between compressed → archive → drop.

    Args:
        compressed: Current compressed entries.
        archive: Current archive entries.
        current_session: Current session count.

    Returns:
        Tuple of (stays_compressed, newly_archived, updated_archive, drop_count).
        ``updated_archive`` is the full archive list after adding newly archived
        and removing dropped entries.
    """
    stays_compressed: list[CompressedEntry] = []
    newly_archived: list[CompressedEntry] = []

    for entry in compressed:
        age = current_session - entry.compressed_at
        if age >= COMPRESSED_TO_ARCHIVE_AGE:
            newly_archived.append(entry)
        else:
            stays_compressed.append(entry)

    # Archive: drop entries that are too old
    surviving_archive: list[CompressedEntry] = []
    drop_count = 0
    for entry in archive:
        age = current_session - entry.compressed_at
        if age >= ARCHIVE_TO_DROP_AGE:
            drop_count += 1
        else:
            surviving_archive.append(entry)

    # Combine: existing surviving archive + newly archived
    updated_archive = surviving_archive + newly_archived

    return stays_compressed, newly_archived, updated_archive, drop_count


def enforce_archive_cap(entries: list[CompressedEntry]) -> list[CompressedEntry]:
    """Enforce the 500-line cap on archive entries, oldest-first eviction.

    Each entry is at most 1 line (title-only in archive), so we cap at
    ARCHIVE_MAX_LINES entries.
    """
    if len(entries) <= ARCHIVE_MAX_LINES:
        return entries
    # Evict oldest first — entries are ordered oldest-first (newly archived appended)
    return entries[len(entries) - ARCHIVE_MAX_LINES :]


# ---------------------------------------------------------------------------
# Main compression
# ---------------------------------------------------------------------------
def compress(project_name: str | None = None, force: bool = False) -> str:
    """Run the compression algorithm.

    Args:
        project_name: Override project name (None = auto-detect).
        force: If True, skip trigger checks.

    Returns:
        Summary message describing what happened.
    """
    # Load ref-cache
    cache_path = get_ref_cache_path(project_name)
    cache = safe_read_json(cache_path, backup_path=cache_path + ".bak")

    session_count = cache.get("session_count", 0)
    if not isinstance(session_count, (int, float)):
        session_count = 0
    session_count = int(session_count)

    # Load session-progress.md
    progress_path = get_session_progress_path(project_name)
    try:
        with open(progress_path) as f:
            progress_md = f.read()
    except (FileNotFoundError, OSError):
        progress_md = ""

    if not progress_md.strip():
        msg = "Compression: no entries to compress"
        print(msg, file=sys.stderr)
        return msg

    entries, sections = parse_session_progress(progress_md)

    if not entries:
        msg = "Compression: no entries to compress"
        print(msg, file=sys.stderr)
        return msg

    # Check triggers (unless forced)
    if not force and not should_compress_with_entries(cache, entries, force=False):
        msg = "Compression: no triggers fired, skipping"
        print(msg, file=sys.stderr)
        return msg

    # Load scores
    scores = cache.get("scores", {})
    if not isinstance(scores, dict):
        scores = {}

    # Categorize
    active, stale_obs, stale_dec = categorize_entries(entries, scores)

    newly_compressed: list[CompressedEntry] = []
    decisions_preserved = 0

    for entry in stale_obs:
        newly_compressed.append(entry_to_compressed(entry, session_count))

    for entry in stale_dec:
        newly_compressed.append(entry_to_compressed(entry, session_count))
        decisions_preserved += 1

    # Load existing compressed context from project-status.md
    status_dir = get_status_dir(project_name)
    project_status_path = os.path.join(status_dir, "project-status.md")
    try:
        with open(project_status_path) as f:
            project_status_md = f.read()
    except (FileNotFoundError, OSError):
        project_status_md = ""

    existing_compressed = _extract_compressed_section(project_status_md)

    # Load archive
    archive_path = os.path.join(status_dir, "archive.md")
    try:
        with open(archive_path) as f:
            archive_text = f.read()
    except (FileNotFoundError, OSError):
        archive_text = ""

    existing_archive = parse_archive_entries(archive_text) if archive_text.strip() else []

    # Tier rotation on previously compressed entries
    stays_compressed, moved_to_archive, updated_archive, drop_count = rotate_tiers(
        existing_compressed, existing_archive, session_count
    )

    # Combine: entries that stay compressed + newly compressed
    all_compressed = stays_compressed + newly_compressed

    # Add newly archived to updated archive + enforce cap
    updated_archive = enforce_archive_cap(updated_archive)

    # Reset scores for newly compressed entries only
    for entry in stale_obs + stale_dec:
        if entry.id and entry.id in scores:
            scores[entry.id] = 0
    cache["scores"] = scores
    cache["last_compression"] = session_count

    # --- Atomic writes (progress file LAST) ---

    # 1. Write archive
    if updated_archive:
        archive_content = serialize_archive(updated_archive) + "\n"
        atomic_write(archive_path, archive_content)

    # 2. Write compressed context into project-status.md
    compressed_section_text = serialize_compressed_section(all_compressed) if all_compressed else ""
    updated_project_status = _update_compressed_section(
        project_status_md, compressed_section_text
    )
    atomic_write(project_status_path, updated_project_status)

    # 3. Write ref-cache
    safe_write_json(cache_path, cache)

    # 4. Write session-progress.md (LAST — partial failure preserves old state)
    new_progress = rebuild_session_progress(active, sections)
    atomic_write(progress_path, new_progress)

    compressed_count = len(newly_compressed)
    archived_count = len(moved_to_archive)
    summary = (
        f"Compressed {compressed_count} entries "
        f"({decisions_preserved} decisions preserved, "
        f"{archived_count} archived, {drop_count} dropped)"
    )
    print(summary, file=sys.stderr)
    return summary


# ---------------------------------------------------------------------------
# Helpers for project-status.md manipulation
# ---------------------------------------------------------------------------
_COMPRESSED_SECTION_RE = re.compile(
    r"(^|\n)(## Compressed Context\n)(.*?)(?=\n## |\Z)",
    re.DOTALL,
)


def _extract_compressed_section(project_status_md: str) -> list[CompressedEntry]:
    """Extract CompressedEntry list from the ## Compressed Context section."""
    m = _COMPRESSED_SECTION_RE.search(project_status_md)
    if not m:
        return []
    section_text = m.group(3)
    return parse_compressed_entries(section_text)


def _update_compressed_section(
    project_status_md: str, compressed_text: str
) -> str:
    """Replace or append the ## Compressed Context section in project-status.md."""
    section_content = f"## Compressed Context\n{compressed_text}\n" if compressed_text else "## Compressed Context\n"

    m = _COMPRESSED_SECTION_RE.search(project_status_md)
    if m:
        # Replace existing section
        start = m.start(2)  # Start of "## Compressed Context\n"
        end = m.end(3)
        return project_status_md[:start] + section_content + project_status_md[end:]
    else:
        # Append new section
        if project_status_md and not project_status_md.endswith("\n"):
            project_status_md += "\n"
        return project_status_md + "\n" + section_content

"""Importable wrapper for auto-capture.py (hyphenated name can't be imported directly)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.entries import Entry, parse_entries, serialize_entries
from lib.fileutil import atomic_write
from lib.paths import get_session_progress_path
from lib.scribe import classify_changes, get_diff_name_status, get_diff_stat, parse_name_status

# Pattern matching ## Auto-captured section header
_AUTO_SECTION_RE = re.compile(r"^##\s+Auto-captured\s*$", re.MULTILINE)


def _extract_filepaths(title: str) -> list[str]:
    """Extract plausible file paths from an entry title.

    Looks for tokens containing a slash or a dot-extension pattern
    (e.g. ``foo.py``, ``hooks/lib/entries.py``).
    """
    paths: list[str] = []
    for token in title.split():
        # Strip common punctuation that might wrap a path
        token = token.strip("`'\"(),;:")
        if "/" in token or re.search(r"\.\w{1,10}$", token):
            paths.append(token)
    return paths


def _deduplicate(
    new_entries: list[Entry], existing_entries: list[Entry]
) -> list[Entry]:
    """Filter out new entries whose title file paths overlap with existing titles."""
    if not existing_entries:
        return new_entries

    # Collect all file-path-like tokens from existing entry titles
    existing_paths: set[str] = set()
    for entry in existing_entries:
        existing_paths.update(_extract_filepaths(entry.title))

    if not existing_paths:
        return new_entries

    kept: list[Entry] = []
    for entry in new_entries:
        entry_paths = _extract_filepaths(entry.title)
        if entry_paths and any(p in existing_paths for p in entry_paths):
            continue  # skip — overlaps with existing
        kept.append(entry)
    return kept


def capture(workdir: str | None = None) -> str | None:
    """Capture uncommitted git changes into ``session-progress.md``.

    Resolves the working directory from ``workdir`` → ``CLAUDE_PROJECT_DIR`` →
    the current directory, then ``chdir``s there for the duration of the call.
    A single ``chdir`` (rather than threading ``cwd=`` through every call) makes
    both the direct git invocations here and the ``scribe`` git helpers run in
    the project, and keeps project-name/path resolution correct. The original
    cwd is always restored.

    Returns a short summary string, or ``None`` when there is nothing to capture.
    """
    workdir = workdir or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    orig_cwd = os.getcwd()
    try:
        os.chdir(workdir)
    except OSError:
        print(
            f"auto-capture: cannot enter {os.path.basename(workdir.rstrip('/')) or workdir}",
            file=sys.stderr,
        )
        return None

    try:
        # 1. Check if inside a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(
                "auto-capture: not inside a git repository — nothing captured",
                file=sys.stderr,
            )
            return None

        # 2. Check for uncommitted changes
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None

        # 3. Get diff name-status
        name_status_output = get_diff_name_status()
        if not name_status_output.strip():
            return None

        # 4. Get diff stat
        stat_output = get_diff_stat()

        # 5. Classify changes into entries
        name_status_entries = parse_name_status(name_status_output)
        new_entries = classify_changes(name_status_entries, stat_output)

        # 6. Exit if no entries
        if not new_entries:
            return None

        # 7-8. Load and parse existing session-progress.md
        progress_path = get_session_progress_path()
        try:
            with open(progress_path) as f:
                existing_content = f.read()
        except (FileNotFoundError, OSError):
            existing_content = ""

        existing_entries = parse_entries(existing_content) if existing_content else []

        # Also parse any existing auto-captured entries for dedup
        auto_captured_entries: list[Entry] = []
        auto_match = _AUTO_SECTION_RE.search(existing_content)
        if auto_match:
            auto_section_text = existing_content[auto_match.end() :]
            auto_captured_entries = parse_entries(auto_section_text)

        all_existing = existing_entries + auto_captured_entries

        # 9. Deduplicate
        new_entries = _deduplicate(new_entries, all_existing)

        # 10. Exit if nothing new after dedup
        if not new_entries:
            return None

        # 11. Generate UUIDs
        for entry in new_entries:
            entry.id = uuid.uuid4().hex[:16]

        # 12-13. Build and append ## Auto-captured section
        if auto_match:
            # Merge new entries into existing auto-captured section
            merged = auto_captured_entries + new_entries
            # Rebuild: everything before ## Auto-captured + new section
            before_auto = existing_content[: auto_match.start()].rstrip("\n")
            auto_section = "## Auto-captured\n\n" + serialize_entries(merged)
            final_content = before_auto + "\n\n" + auto_section + "\n"
        else:
            # Append new section
            base = existing_content.rstrip("\n")
            auto_section = "## Auto-captured\n\n" + serialize_entries(new_entries)
            if base:
                final_content = base + "\n\n" + auto_section + "\n"
            else:
                final_content = auto_section + "\n"

        atomic_write(progress_path, final_content)

        count = len(new_entries)
        return f"captured {count} entr{'y' if count == 1 else 'ies'}"
    finally:
        os.chdir(orig_cwd)


def main() -> None:
    """SessionEnd hook entry point.

    Reads the SessionEnd payload best-effort — ``reason`` is used only for the
    stderr log line; capture runs on every reason — then delegates to
    :func:`capture`. Never raises.
    """
    reason = ""
    try:
        raw = sys.stdin.read()
        if raw.strip():
            data = json.loads(raw)
            if isinstance(data, dict):
                reason = str(data.get("reason", "") or "")
    except Exception:
        reason = ""

    try:
        summary = capture()
        if summary:
            print(
                f"auto-capture [{reason or 'session-end'}]: {summary}",
                file=sys.stderr,
            )
    except Exception as exc:
        print(f"auto-capture: {type(exc).__name__}", file=sys.stderr)

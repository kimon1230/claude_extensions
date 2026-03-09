"""Parse and serialize typed entries from session-progress.md markdown files."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Pattern: ### [type] title <!-- id:hex -->
_HEADER_RE = re.compile(
    r"^###\s+\[(\w+)]\s+(.*?)(?:\s*<!--\s*id:([0-9a-fA-F]+)\s*-->)?\s*$"
)

# Pattern: - bullet text (legacy format)
_BULLET_RE = re.compile(r"^-\s+(.+)$")

# Section header: **SectionName** (bold text on its own line)
_SECTION_RE = re.compile(r"^\*\*(.+?)\*\*\s*$")


@dataclass
class Entry:
    """A single decision or observation entry."""

    type: str  # "decision" or "observation"
    title: str  # The entry title text
    why: str  # Sacred Why: text for decisions, empty for observations
    body: str  # What: text for decisions, or plain body for observations
    id: str | None  # UUID like "a1b2c3d4e5f6a7b8" (16 hex chars), None for legacy


def parse_entries(markdown: str) -> list[Entry]:
    """Parse typed entry headers from markdown text.

    If no ``### [type]`` headers are found, falls back to treating ``- `` bullets
    under a **Completed** section as observations with ``id=None``.
    """
    lines = markdown.split("\n")
    entries: list[Entry] = []
    current: Entry | None = None
    body_lines: list[str] = []
    found_typed = False

    def _flush() -> None:
        if current is None:
            return
        raw_body = "\n".join(body_lines).strip()
        if current.type == "decision":
            current.why, current.body = _extract_why_what(raw_body)
        else:
            current.body = raw_body

    for line in lines:
        m = _HEADER_RE.match(line)
        if m:
            _flush()
            found_typed = True
            entry_type, title, entry_id = m.group(1), m.group(2).strip(), m.group(3)
            current = Entry(
                type=entry_type, title=title, why="", body="", id=entry_id
            )
            entries.append(current)
            body_lines = []
        elif current is not None:
            body_lines.append(line)

    _flush()

    if not found_typed:
        return _parse_legacy_bullets(markdown)

    return entries


def _extract_why_what(text: str) -> tuple[str, str]:
    """Extract Why: and What: values from decision body text."""
    why = ""
    what = ""
    other_lines: list[str] = []

    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.lower().startswith("why:"):
            why = stripped[4:].strip()
        elif stripped.lower().startswith("what:"):
            what = stripped[5:].strip()
        else:
            other_lines.append(line)

    # If there's no explicit What: but there are remaining non-empty lines,
    # treat them as body content.
    remaining = "\n".join(other_lines).strip()
    if not what and remaining:
        what = remaining

    return why, what


def _parse_legacy_bullets(markdown: str) -> list[Entry]:
    """Parse legacy format: ``- `` bullets under **Completed** section."""
    entries: list[Entry] = []
    in_completed = False

    for line in markdown.split("\n"):
        section_m = _SECTION_RE.match(line)
        if section_m:
            in_completed = section_m.group(1).strip().lower() == "completed"
            continue

        if in_completed:
            bullet_m = _BULLET_RE.match(line.strip())
            if bullet_m:
                entries.append(
                    Entry(
                        type="observation",
                        title=bullet_m.group(1).strip(),
                        why="",
                        body="",
                        id=None,
                    )
                )

    return entries


def serialize_entries(entries: list[Entry]) -> str:
    """Serialize entries to markdown ``### [type] title`` format."""
    blocks: list[str] = []
    for entry in entries:
        id_suffix = f" <!-- id:{entry.id} -->" if entry.id else ""
        header = f"### [{entry.type}] {entry.title}{id_suffix}"
        body_parts: list[str] = []
        if entry.type == "decision":
            if entry.why:
                body_parts.append(f"Why: {entry.why}")
            if entry.body:
                body_parts.append(f"What: {entry.body}")
        else:
            if entry.body:
                body_parts.append(entry.body)
        if body_parts:
            blocks.append(header + "\n" + "\n".join(body_parts))
        else:
            blocks.append(header)
    return "\n\n".join(blocks)


def parse_session_progress(markdown: str) -> tuple[list[Entry], dict[str, str]]:
    """Section-aware parse of a full session-progress.md file.

    Returns:
        A tuple of (entries from **Completed**, dict of preserved sections).
        The sections dict has keys: ``"preamble"`` for content before **Completed**,
        ``"post_completed"`` for content after entries but before next section,
        and each subsequent ``**Section**`` header as a key with its content.
    """
    lines = markdown.split("\n")
    sections: dict[str, str] = {}
    section_order: list[str] = []

    # Find all **Section** boundaries
    boundaries: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line)
        if m:
            boundaries.append((i, m.group(1).strip()))

    completed_idx: int | None = None

    for idx, (line_no, name) in enumerate(boundaries):
        if name.lower() == "completed":
            completed_idx = idx
            break

    if completed_idx is None:
        # No **Completed** section found — entire file is preamble
        sections["preamble"] = markdown
        section_order.append("preamble")
        return [], sections

    comp_line_no = boundaries[completed_idx][0]

    # Preamble: everything before the **Completed** line
    preamble_lines = lines[:comp_line_no]
    sections["preamble"] = "\n".join(preamble_lines)
    section_order.append("preamble")

    # Determine end of completed section
    if completed_idx + 1 < len(boundaries):
        next_line_no = boundaries[completed_idx + 1][0]
    else:
        next_line_no = len(lines)

    # Content between **Completed** header and next section
    completed_content_lines = lines[comp_line_no + 1 : next_line_no]
    completed_content = "\n".join(completed_content_lines)

    # Parse entries from the completed section content
    entries = parse_entries(completed_content)

    # If typed entries were found, compute post_completed as any trailing
    # non-entry content. For simplicity, post_completed captures trailing
    # whitespace/blank lines after the last entry within the completed block.
    # Since parse_entries consumes all typed content, post_completed is empty
    # unless there's trailing non-entry text.
    sections["post_completed"] = ""
    section_order.append("post_completed")

    # Remaining sections after completed
    for idx in range(completed_idx + 1, len(boundaries)):
        line_no = boundaries[idx][0]
        name = boundaries[idx][1]
        if idx + 1 < len(boundaries):
            end_no = boundaries[idx + 1][0]
        else:
            end_no = len(lines)
        section_content = "\n".join(lines[line_no + 1 : end_no])
        sections[name] = section_content
        section_order.append(name)

    # Store order for rebuild
    sections["_order"] = "\n".join(section_order)

    return entries, sections


def rebuild_session_progress(entries: list[Entry], sections: dict[str, str]) -> str:
    """Reconstruct a full session-progress.md from entries and preserved sections.

    Entries are placed under a **Completed** header. Other sections appear in
    their original order.
    """
    order_raw = sections.get("_order", "")
    if order_raw:
        order = order_raw.split("\n")
    else:
        order = [k for k in sections if k != "_order"]

    parts: list[str] = []

    for key in order:
        if key == "preamble":
            preamble = sections.get("preamble", "")
            if preamble:
                parts.append(preamble)
        elif key == "post_completed":
            # Insert **Completed** header + serialized entries
            parts.append("**Completed**")
            serialized = serialize_entries(entries)
            if serialized:
                parts.append(serialized)
            post = sections.get("post_completed", "")
            if post.strip():
                parts.append(post)
        else:
            content = sections.get(key, "")
            parts.append(f"**{key}**")
            if content.strip():
                parts.append(content)

    return "\n".join(parts)

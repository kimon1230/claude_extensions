"""Importable wrapper for session-init.py (hyphenated name can't be imported directly)."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.entries import Entry, parse_entries
from lib.fileutil import safe_read_json, safe_write_json
from lib.paths import get_ref_cache_path, get_session_progress_path

# Sources on which we re-inject persisted context. `compact` re-fires after both
# auto and manual context compaction (Claude Code re-runs SessionStart to refresh
# stale context); `resume`/`startup` cover normal session entry.
_INJECT_SOURCES = ("startup", "resume", "compact")

# Hard cap on the injected `additionalContext` string. The documented hook limit
# is 10,000 chars; 4 KB keeps the injection cheap while covering most active work.
_INJECT_CAP = 4096

# Max length of a decision's `Why:` text in the summary.
_WHY_CAP = 200


def _read_source() -> str:
    """Read the SessionStart ``source`` from stdin (best-effort).

    Returns the source string, defaulting to ``"startup"`` when stdin is
    absent/unreadable or carries no usable ``source`` (so fresh sessions still
    receive context).
    """
    try:
        raw = sys.stdin.read()
        if raw.strip():
            data = json.loads(raw)
            if isinstance(data, dict):
                src = data.get("source")
                if isinstance(src, str) and src:
                    return src
    except Exception:
        pass
    return "startup"


def build_injection(entries: list[Entry], cap: int = _INJECT_CAP) -> str:
    """Build a recency-ordered context summary, hard-capped at ``cap`` chars.

    Entries are emitted most-recent-first (they are appended chronologically, so
    the tail is newest). Decisions include a truncated ``Why:``. Returns an empty
    string when there are no entries.
    """
    if not entries:
        return ""

    header = (
        "Persisted session context (most recent first; "
        "full history in ~/.claude/status/):"
    )
    reserve = 80  # room for the trailing "… N omitted" note
    budget = cap - reserve
    max_line = budget - len(header) - 1

    lines: list[str] = []
    used = len(header) + 1
    for entry in reversed(entries):  # newest first
        why = ""
        if entry.type == "decision" and entry.why:
            collapsed = " ".join(entry.why.split())
            if len(collapsed) > _WHY_CAP:
                collapsed = collapsed[: _WHY_CAP - 3] + "..."
            why = f" — Why: {collapsed}"
        line = f"- [{entry.type}] {entry.title}{why}"
        if len(line) > max_line:
            line = line[: max_line - 3].rstrip() + "..."
        if lines and used + len(line) + 1 > budget:
            break
        lines.append(line)
        used += len(line) + 1
        if used >= budget:
            break

    omitted = len(entries) - len(lines)
    text = header + "\n" + "\n".join(lines)
    if omitted > 0:
        text += f"\n… {omitted} earlier entr{'y' if omitted == 1 else 'ies'} omitted"
    return text


def main() -> None:
    """Increment the session count and (on entry/resume/compaction) re-inject context.

    Diagnostics go to stderr; stdout carries **only** the SessionStart
    ``additionalContext`` JSON object (or nothing) so Claude Code can parse it.
    """
    try:
        cache_path = get_ref_cache_path()
        cache = safe_read_json(cache_path, backup_path=cache_path + ".bak")

        session_count = cache.get("session_count", 0)
        if not isinstance(session_count, (int, float)):
            session_count = 0
        cache["session_count"] = int(session_count) + 1
        cache["last_updated"] = datetime.now(timezone.utc).isoformat()

        safe_write_json(cache_path, cache)

        progress_path = get_session_progress_path()
        try:
            with open(progress_path) as f:
                markdown = f.read()
        except (FileNotFoundError, OSError):
            markdown = ""

        entries = parse_entries(markdown)
        print(f"Context: {len(entries)} entries", file=sys.stderr)

        # Re-inject persisted context so the model regains working state on
        # session start/resume and — crucially — after a native compaction.
        if _read_source() in _INJECT_SOURCES:
            summary = build_injection(entries)
            if summary:
                payload = {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": summary,
                    }
                }
                print(json.dumps(payload))

    except Exception as exc:
        print(f"session-init: {type(exc).__name__}", file=sys.stderr)

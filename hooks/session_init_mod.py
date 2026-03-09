"""Importable wrapper for session-init.py (hyphenated name can't be imported directly)."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.entries import parse_entries
from lib.fileutil import safe_read_json, safe_write_json
from lib.paths import get_ref_cache_path, get_session_progress_path


def main() -> None:
    """Increment session count and print context summary."""
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
        scores = cache.get("scores", {})
        if not isinstance(scores, dict):
            scores = {}

        total = len(entries)
        active = sum(
            1
            for e in entries
            if e.id is not None and scores.get(e.id, 0) > 0
        )
        stale = sum(
            1
            for e in entries
            if e.id is not None and scores.get(e.id, 0) == 0
        )

        print(
            f"Context: {total} entries, {active} active, {stale} stale",
            file=sys.stderr,
        )

        # Check compression triggers
        from lib.compressor import compress, should_compress_with_entries

        if should_compress_with_entries(cache, entries):
            try:
                summary = compress()
                print(f"Auto-compression: {summary}", file=sys.stderr)
            except Exception:
                pass

    except Exception as exc:
        print(f"session-init: {type(exc).__name__}", file=sys.stderr)

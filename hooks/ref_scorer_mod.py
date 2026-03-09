"""Importable wrapper for ref-scorer.py (hyphenated name can't be imported directly)."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.entries import parse_entries
from lib.fileutil import safe_read_json, safe_write_json
from lib.paths import get_ref_cache_path, get_session_progress_path
from lib.ref_tracker import extract_context_from_tool_input, score_entry


def main() -> None:
    """Score session-progress entries against the current tool context."""
    try:
        raw = sys.stdin.read(1_000_000)  # 1MB limit (CWE-400)
        if not raw:
            return

        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return

        if not isinstance(payload, dict):
            return

        tool_paths, tool_keywords = extract_context_from_tool_input(payload)
        if not tool_paths and not tool_keywords:
            return

        progress_path = get_session_progress_path()
        try:
            with open(progress_path) as f:
                markdown = f.read()
        except (FileNotFoundError, OSError):
            return

        entries = parse_entries(markdown)
        if not entries:
            return

        cache_path = get_ref_cache_path()
        cache = safe_read_json(cache_path, backup_path=cache_path + ".bak")

        scores = cache.get("scores", {})
        if not isinstance(scores, dict):
            scores = {}

        for entry in entries:
            if entry.id is None:
                continue
            delta = score_entry(entry, tool_paths, tool_keywords)
            if delta > 0:
                current = scores.get(entry.id, 0)
                if not isinstance(current, (int, float)):
                    current = 0
                scores[entry.id] = current + delta

        cache["scores"] = scores
        safe_write_json(cache_path, cache)

    except Exception as exc:
        print(f"ref-scorer: {type(exc).__name__}", file=sys.stderr)

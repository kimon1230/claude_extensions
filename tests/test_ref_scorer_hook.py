"""Tests for hooks/ref-scorer.py PostToolUse hook."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hooks.lib.entries import Entry, serialize_entries
from hooks.lib.fileutil import safe_read_json

# Import the module under test eagerly so monkeypatch targets are stable
from hooks import ref_scorer_mod


def _make_progress_md(entries: list[Entry]) -> str:
    """Build a minimal session-progress.md from entries."""
    return "**Completed**\n" + serialize_entries(entries)


def _make_payload(
    tool_name: str = "Read",
    file_path: str | None = None,
    pattern: str | None = None,
    old_string: str | None = None,
    new_string: str | None = None,
) -> dict:
    """Build a PostToolUse hook payload."""
    tool_input: dict = {}
    if file_path is not None:
        tool_input["file_path"] = file_path
    if pattern is not None:
        tool_input["pattern"] = pattern
    if old_string is not None:
        tool_input["old_string"] = old_string
    if new_string is not None:
        tool_input["new_string"] = new_string
    return {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_response": {},
        "cwd": "/project",
    }


class TestRefScorerProcessesReadPayload:
    def test_read_payload_updates_cache(self, tmp_path, monkeypatch):
        """Hook processes a valid Read payload and updates cache scores."""
        progress_path = str(tmp_path / "session-progress.md")
        cache_path = str(tmp_path / "ref-cache.json")

        entry = Entry(
            type="observation",
            title="Added hooks/lib/entries.py parser",
            why="",
            body="Parses entries from hooks/lib/entries.py file.",
            id="aabb112233445566",
        )
        with open(progress_path, "w") as f:
            f.write(_make_progress_md([entry]))

        payload = _make_payload(
            tool_name="Read", file_path="hooks/lib/entries.py"
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        monkeypatch.setattr(
            ref_scorer_mod,
            "get_session_progress_path",
            lambda *a, **kw: progress_path,
        )
        monkeypatch.setattr(
            ref_scorer_mod,
            "get_ref_cache_path",
            lambda *a, **kw: cache_path,
        )

        ref_scorer_mod.main()

        cache = safe_read_json(cache_path)
        assert "scores" in cache
        assert cache["scores"]["aabb112233445566"] > 0


class TestRefScorerProcessesEditPayload:
    def test_edit_payload_with_keywords(self, tmp_path, monkeypatch):
        """Hook processes Edit payload with keywords and updates cache."""
        progress_path = str(tmp_path / "session-progress.md")
        cache_path = str(tmp_path / "ref-cache.json")

        entry = Entry(
            type="decision",
            title="Implemented scoring algorithm with weighted tiers",
            why="Need relevance ranking for context retrieval",
            body="Added weighted scoring with directory overlap detection",
            id="ccdd112233445566",
        )
        with open(progress_path, "w") as f:
            f.write(_make_progress_md([entry]))

        payload = _make_payload(
            tool_name="Edit",
            file_path="src/scoring.py",
            old_string="scoring algorithm weighted tiers relevance ranking",
            new_string="scoring algorithm weighted tiers relevance ranking updated",
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        monkeypatch.setattr(
            ref_scorer_mod,
            "get_session_progress_path",
            lambda *a, **kw: progress_path,
        )
        monkeypatch.setattr(
            ref_scorer_mod,
            "get_ref_cache_path",
            lambda *a, **kw: cache_path,
        )

        ref_scorer_mod.main()

        cache = safe_read_json(cache_path)
        assert "scores" in cache
        assert cache["scores"]["ccdd112233445566"] > 0


class TestRefScorerSilentExits:
    def test_empty_stdin(self, monkeypatch):
        """Hook exits silently on empty stdin."""
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        ref_scorer_mod.main()

    def test_malformed_json(self, monkeypatch):
        """Hook exits silently on malformed JSON."""
        monkeypatch.setattr("sys.stdin", io.StringIO("{not valid json!!!"))
        ref_scorer_mod.main()

    def test_no_session_progress(self, tmp_path, monkeypatch):
        """Hook exits silently when no session-progress.md exists."""
        progress_path = str(tmp_path / "nonexistent-progress.md")
        cache_path = str(tmp_path / "ref-cache.json")

        payload = _make_payload(tool_name="Read", file_path="src/main.py")
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        monkeypatch.setattr(
            ref_scorer_mod,
            "get_session_progress_path",
            lambda *a, **kw: progress_path,
        )
        monkeypatch.setattr(
            ref_scorer_mod,
            "get_ref_cache_path",
            lambda *a, **kw: cache_path,
        )

        ref_scorer_mod.main()

        # Cache should not have been created
        assert not os.path.exists(cache_path)

    def test_exception_is_swallowed(self, monkeypatch):
        """Hook exits silently on any exception (mock a failure)."""
        payload = _make_payload(tool_name="Read", file_path="src/main.py")
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))

        # Force extract_context_from_tool_input to raise
        monkeypatch.setattr(
            ref_scorer_mod,
            "extract_context_from_tool_input",
            lambda _: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        # Should not raise despite the RuntimeError
        ref_scorer_mod.main()


class TestRefScorerEdgeCases:
    def test_no_context_exits_early(self, monkeypatch):
        """Hook exits early when tool input yields no paths or keywords."""
        payload = {"tool_name": "Read", "tool_input": {}, "tool_response": {}}
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        ref_scorer_mod.main()

    def test_entries_without_ids_skipped(self, tmp_path, monkeypatch):
        """Entries without ids are skipped (no crash, no score)."""
        progress_path = str(tmp_path / "session-progress.md")
        cache_path = str(tmp_path / "ref-cache.json")

        entry = Entry(
            type="observation",
            title="Legacy entry about hooks/lib/entries.py",
            why="",
            body="Some body mentioning hooks/lib/entries.py",
            id=None,
        )
        with open(progress_path, "w") as f:
            f.write(_make_progress_md([entry]))

        payload = _make_payload(
            tool_name="Read", file_path="hooks/lib/entries.py"
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        monkeypatch.setattr(
            ref_scorer_mod,
            "get_session_progress_path",
            lambda *a, **kw: progress_path,
        )
        monkeypatch.setattr(
            ref_scorer_mod,
            "get_ref_cache_path",
            lambda *a, **kw: cache_path,
        )

        ref_scorer_mod.main()

        cache = safe_read_json(cache_path)
        assert cache.get("scores", {}) == {}

    def test_accumulates_scores(self, tmp_path, monkeypatch):
        """Scores accumulate across multiple calls."""
        progress_path = str(tmp_path / "session-progress.md")
        cache_path = str(tmp_path / "ref-cache.json")

        entry = Entry(
            type="observation",
            title="Added hooks/lib/entries.py parser",
            why="",
            body="Parses entries from hooks/lib/entries.py file.",
            id="aabb112233445566",
        )
        with open(progress_path, "w") as f:
            f.write(_make_progress_md([entry]))

        payload = _make_payload(
            tool_name="Read", file_path="hooks/lib/entries.py"
        )

        monkeypatch.setattr(
            ref_scorer_mod,
            "get_session_progress_path",
            lambda *a, **kw: progress_path,
        )
        monkeypatch.setattr(
            ref_scorer_mod,
            "get_ref_cache_path",
            lambda *a, **kw: cache_path,
        )

        # First call
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        ref_scorer_mod.main()

        first_score = safe_read_json(cache_path)["scores"]["aabb112233445566"]

        # Second call
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        ref_scorer_mod.main()

        second_score = safe_read_json(cache_path)["scores"]["aabb112233445566"]
        assert second_score > first_score

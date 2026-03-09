"""Tests for hooks/session-init.py SessionStart hook."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hooks.lib.entries import Entry, serialize_entries
from hooks.lib.fileutil import safe_read_json, safe_write_json

# Import the module under test eagerly so monkeypatch targets are stable
from hooks import session_init_mod


def _make_progress_md(entries: list[Entry]) -> str:
    """Build a minimal session-progress.md from entries."""
    return "**Completed**\n" + serialize_entries(entries)


class TestSessionCountIncrement:
    def test_increments_from_zero(self, tmp_path, monkeypatch):
        """First run increments session_count from 0 to 1."""
        cache_path = str(tmp_path / "ref-cache.json")
        progress_path = str(tmp_path / "session-progress.md")

        monkeypatch.setattr(
            session_init_mod,
            "get_ref_cache_path",
            lambda *a, **kw: cache_path,
        )
        monkeypatch.setattr(
            session_init_mod,
            "get_session_progress_path",
            lambda *a, **kw: progress_path,
        )

        session_init_mod.main()

        cache = safe_read_json(cache_path)
        assert cache["session_count"] == 1

    def test_increments_existing_count(self, tmp_path, monkeypatch):
        """Increments an already-set session_count."""
        cache_path = str(tmp_path / "ref-cache.json")
        progress_path = str(tmp_path / "session-progress.md")

        safe_write_json(cache_path, {"session_count": 5})

        monkeypatch.setattr(
            session_init_mod,
            "get_ref_cache_path",
            lambda *a, **kw: cache_path,
        )
        monkeypatch.setattr(
            session_init_mod,
            "get_session_progress_path",
            lambda *a, **kw: progress_path,
        )

        session_init_mod.main()

        cache = safe_read_json(cache_path)
        assert cache["session_count"] == 6


class TestCacheCreation:
    def test_creates_cache_on_first_run(self, tmp_path, monkeypatch):
        """Creates ref-cache.json when it does not exist."""
        cache_path = str(tmp_path / "ref-cache.json")
        progress_path = str(tmp_path / "session-progress.md")

        assert not os.path.exists(cache_path)

        monkeypatch.setattr(
            session_init_mod,
            "get_ref_cache_path",
            lambda *a, **kw: cache_path,
        )
        monkeypatch.setattr(
            session_init_mod,
            "get_session_progress_path",
            lambda *a, **kw: progress_path,
        )

        session_init_mod.main()

        assert os.path.exists(cache_path)
        cache = safe_read_json(cache_path)
        assert cache["session_count"] == 1
        assert "last_updated" in cache

    def test_handles_missing_cache_gracefully(self, tmp_path, monkeypatch):
        """Does not crash when cache file is missing (creates parent dirs)."""
        cache_path = str(tmp_path / "nonexistent" / "ref-cache.json")
        progress_path = str(tmp_path / "session-progress.md")

        monkeypatch.setattr(
            session_init_mod,
            "get_ref_cache_path",
            lambda *a, **kw: cache_path,
        )
        monkeypatch.setattr(
            session_init_mod,
            "get_session_progress_path",
            lambda *a, **kw: progress_path,
        )

        # Should not raise
        session_init_mod.main()

        cache = safe_read_json(cache_path)
        assert cache["session_count"] == 1


class TestContextSummary:
    def test_logs_summary_to_stderr(self, tmp_path, monkeypatch, capsys):
        """Prints context summary to stderr."""
        cache_path = str(tmp_path / "ref-cache.json")
        progress_path = str(tmp_path / "session-progress.md")

        entries = [
            Entry("observation", "Entry A", "", "body", "aaaa000000000001"),
            Entry("decision", "Entry B", "why", "what", "aaaa000000000002"),
        ]
        with open(progress_path, "w") as f:
            f.write(_make_progress_md(entries))

        # Pre-seed cache with a score for entry A
        safe_write_json(
            cache_path,
            {"session_count": 2, "scores": {"aaaa000000000001": 3}},
        )

        monkeypatch.setattr(
            session_init_mod,
            "get_ref_cache_path",
            lambda *a, **kw: cache_path,
        )
        monkeypatch.setattr(
            session_init_mod,
            "get_session_progress_path",
            lambda *a, **kw: progress_path,
        )

        session_init_mod.main()

        captured = capsys.readouterr()
        assert "Context: 2 entries, 1 active, 1 stale" in captured.err

    def test_handles_missing_progress_file(self, tmp_path, monkeypatch, capsys):
        """Still increments count when session-progress.md is missing."""
        cache_path = str(tmp_path / "ref-cache.json")
        progress_path = str(tmp_path / "nonexistent-progress.md")

        monkeypatch.setattr(
            session_init_mod,
            "get_ref_cache_path",
            lambda *a, **kw: cache_path,
        )
        monkeypatch.setattr(
            session_init_mod,
            "get_session_progress_path",
            lambda *a, **kw: progress_path,
        )

        session_init_mod.main()

        cache = safe_read_json(cache_path)
        assert cache["session_count"] == 1

        captured = capsys.readouterr()
        assert "Context: 0 entries, 0 active, 0 stale" in captured.err

    def test_sets_last_updated_timestamp(self, tmp_path, monkeypatch):
        """Sets last_updated to an ISO format timestamp."""
        cache_path = str(tmp_path / "ref-cache.json")
        progress_path = str(tmp_path / "session-progress.md")

        monkeypatch.setattr(
            session_init_mod,
            "get_ref_cache_path",
            lambda *a, **kw: cache_path,
        )
        monkeypatch.setattr(
            session_init_mod,
            "get_session_progress_path",
            lambda *a, **kw: progress_path,
        )

        session_init_mod.main()

        cache = safe_read_json(cache_path)
        ts = cache["last_updated"]
        # Should be a valid ISO format string with timezone info
        assert "T" in ts
        assert "+" in ts or "Z" in ts


class TestSessionInitErrorHandling:
    def test_swallows_exceptions(self, monkeypatch):
        """Does not crash on unexpected errors."""
        # Force get_ref_cache_path to raise
        monkeypatch.setattr(
            session_init_mod,
            "get_ref_cache_path",
            lambda *a, **kw: (_ for _ in ()).throw(
                RuntimeError("forced failure")
            ),
        )

        # Should not raise
        session_init_mod.main()

"""Tests for hooks/session-init.py SessionStart hook."""

from __future__ import annotations

import io
import json
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
        assert "Context: 2 entries" in captured.err
        assert "active" not in captured.err

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
        assert "Context: 0 entries" in captured.err

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


def _ctx_entries() -> list[Entry]:
    return [
        Entry("observation", "Did thing A", "", "body A", "aaaa000000000001"),
        Entry(
            "decision",
            "Chose B over C",
            "because B is faster and simpler",
            "what B",
            "aaaa000000000002",
        ),
    ]


class TestContextInjection:
    def _setup(self, tmp_path, monkeypatch, entries):
        cache_path = str(tmp_path / "ref-cache.json")
        progress_path = str(tmp_path / "session-progress.md")
        with open(progress_path, "w") as f:
            f.write(_make_progress_md(entries))
        monkeypatch.setattr(
            session_init_mod, "get_ref_cache_path", lambda *a, **kw: cache_path
        )
        monkeypatch.setattr(
            session_init_mod, "get_session_progress_path", lambda *a, **kw: progress_path
        )

    def test_emits_single_json_object_on_stdout(self, tmp_path, monkeypatch, capsys):
        """stdout is exactly one decodable SessionStart additionalContext object."""
        self._setup(tmp_path, monkeypatch, _ctx_entries())
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"source": "compact"})))

        session_init_mod.main()

        data = json.loads(capsys.readouterr().out)  # raises if not pure JSON
        ctx = data["hookSpecificOutput"]["additionalContext"]
        assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "Chose B over C" in ctx
        assert "because B is faster" in ctx  # decision Why is included

    def test_diagnostics_stay_on_stderr_only(self, tmp_path, monkeypatch, capsys):
        self._setup(tmp_path, monkeypatch, _ctx_entries())
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"source": "startup"})))

        session_init_mod.main()

        captured = capsys.readouterr()
        assert "Context: 2 entries" in captured.err
        assert "Context:" not in captured.out
        json.loads(captured.out)  # stdout must be pure JSON

    def test_absent_source_defaults_to_startup_and_injects(
        self, tmp_path, monkeypatch, capsys
    ):
        self._setup(tmp_path, monkeypatch, _ctx_entries())
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "x"})))

        session_init_mod.main()

        data = json.loads(capsys.readouterr().out)
        assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"

    def test_ungated_source_emits_nothing_on_stdout(self, tmp_path, monkeypatch, capsys):
        self._setup(tmp_path, monkeypatch, _ctx_entries())
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"source": "clear"})))

        session_init_mod.main()

        captured = capsys.readouterr()
        assert captured.out.strip() == ""  # no injection for 'clear'
        assert "Context: 2 entries" in captured.err  # session still logged

    def test_malformed_stdin_defaults_to_startup(self, tmp_path, monkeypatch, capsys):
        self._setup(tmp_path, monkeypatch, _ctx_entries())
        monkeypatch.setattr("sys.stdin", io.StringIO("not json {{{"))

        session_init_mod.main()  # must not raise

        data = json.loads(capsys.readouterr().out)
        assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"

    def test_payload_capped_and_notes_omitted(self, tmp_path, monkeypatch, capsys):
        entries = [
            Entry("decision", f"Decision number {i}", "x" * 300, "body", f"{i:016x}")
            for i in range(200)
        ]
        self._setup(tmp_path, monkeypatch, entries)
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"source": "resume"})))

        session_init_mod.main()

        ctx = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
        assert len(ctx) <= session_init_mod._INJECT_CAP
        assert "omitted" in ctx

    def test_no_entries_emits_nothing(self, tmp_path, monkeypatch, capsys):
        self._setup(tmp_path, monkeypatch, [])
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"source": "startup"})))

        session_init_mod.main()

        assert capsys.readouterr().out.strip() == ""

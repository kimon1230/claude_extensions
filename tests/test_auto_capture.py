"""Tests for hooks/auto-capture.py Stop hook."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hooks.lib.entries import Entry, serialize_entries
from hooks.lib.fileutil import safe_read_json

# Import the module under test eagerly so monkeypatch targets are stable
from hooks import auto_capture_mod


def _make_entry(
    title: str,
    entry_type: str = "observation",
    body: str = "",
    entry_id: str | None = "aabb112233445566",
) -> Entry:
    return Entry(type=entry_type, title=title, why="", body=body, id=entry_id)


def _make_progress_md(entries: list[Entry], sections: dict[str, str] | None = None) -> str:
    """Build a session-progress.md with **Completed** section and optional extra sections."""
    parts = ["**Completed**\n" + serialize_entries(entries)]
    if sections:
        for header, content in sections.items():
            parts.append(f"**{header}**\n{content}")
    return "\n\n".join(parts)


def _setup_git_mocks(monkeypatch, *, in_repo: bool = True, has_changes: bool = True):
    """Mock subprocess.run for git commands."""
    original_run = subprocess.run

    def mock_run(cmd, **kwargs):
        if cmd[:3] == ["git", "rev-parse", "--is-inside-work-tree"]:
            if in_repo:
                return subprocess.CompletedProcess(cmd, 0, stdout="true\n", stderr="")
            return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="fatal")
        if cmd[:3] == ["git", "status", "--porcelain"]:
            if has_changes:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=" M src/main.py\n", stderr=""
                )
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return original_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", mock_run)


def _setup_scribe_mocks(
    monkeypatch,
    *,
    name_status: str = "M\tsrc/main.py",
    stat: str = " src/main.py | 5 +++--",
    entries: list[Entry] | None = None,
):
    """Mock scribe functions."""
    if entries is None:
        entries = [
            _make_entry("Modified src/main.py", entry_id=None, body="Updated main module")
        ]

    monkeypatch.setattr(auto_capture_mod, "get_diff_name_status", lambda: name_status)
    monkeypatch.setattr(auto_capture_mod, "get_diff_stat", lambda: stat)
    monkeypatch.setattr(
        auto_capture_mod, "parse_name_status", lambda output: [("M", "src/main.py", None)]
    )
    monkeypatch.setattr(
        auto_capture_mod, "classify_changes", lambda ns, st: list(entries)
    )


def _setup_paths(monkeypatch, tmp_path):
    """Mock path functions to use tmp_path."""
    progress_path = str(tmp_path / "session-progress.md")
    cache_path = str(tmp_path / "ref-cache.json")

    monkeypatch.setattr(
        auto_capture_mod, "get_session_progress_path", lambda *a, **kw: progress_path
    )
    monkeypatch.setattr(
        auto_capture_mod, "get_ref_cache_path", lambda *a, **kw: cache_path
    )
    return progress_path, cache_path


class TestAutoCapturAppendsEntries:
    def test_appends_auto_captured_entries(self, tmp_path, monkeypatch):
        """Auto-captured entries are appended to session-progress.md."""
        _setup_git_mocks(monkeypatch)
        _setup_scribe_mocks(monkeypatch)
        progress_path, cache_path = _setup_paths(monkeypatch, tmp_path)

        # Write existing progress file
        existing = _make_progress_md([_make_entry("Existing work on src/other.py")])
        with open(progress_path, "w") as f:
            f.write(existing)

        auto_capture_mod.main()

        with open(progress_path) as f:
            content = f.read()

        assert "## Auto-captured" in content
        assert "src/main.py" in content
        # Existing content preserved
        assert "**Completed**" in content
        assert "Existing work on src/other.py" in content


class TestPreservesExistingSections:
    def test_preserves_completed_and_other_sections(self, tmp_path, monkeypatch):
        """Existing Completed entries and other sections are preserved."""
        _setup_git_mocks(monkeypatch)
        _setup_scribe_mocks(monkeypatch)
        progress_path, cache_path = _setup_paths(monkeypatch, tmp_path)

        existing = _make_progress_md(
            [_make_entry("Existing entry about src/utils.py")],
            sections={"Notes": "Some important notes here"},
        )
        with open(progress_path, "w") as f:
            f.write(existing)

        auto_capture_mod.main()

        with open(progress_path) as f:
            content = f.read()

        assert "**Completed**" in content
        assert "Existing entry about src/utils.py" in content
        assert "**Notes**" in content
        assert "Some important notes here" in content
        assert "## Auto-captured" in content


class TestDeduplication:
    def test_skips_entries_with_overlapping_filepaths(self, tmp_path, monkeypatch):
        """Entries whose title mentions a file already in existing entries are skipped."""
        _setup_git_mocks(monkeypatch)
        # New entry title contains "src/main.py" which is also in existing
        _setup_scribe_mocks(
            monkeypatch,
            entries=[_make_entry("Modified src/main.py", entry_id=None)],
        )
        progress_path, cache_path = _setup_paths(monkeypatch, tmp_path)

        existing = _make_progress_md(
            [_make_entry("Refactored src/main.py handler")]
        )
        with open(progress_path, "w") as f:
            f.write(existing)

        auto_capture_mod.main()

        with open(progress_path) as f:
            content = f.read()

        # No auto-captured section should be added since the entry was deduped
        assert "## Auto-captured" not in content

    def test_keeps_entries_with_new_filepaths(self, tmp_path, monkeypatch):
        """Entries with filepaths not in existing entries are kept."""
        _setup_git_mocks(monkeypatch)
        _setup_scribe_mocks(
            monkeypatch,
            entries=[_make_entry("Added src/new_module.py", entry_id=None)],
        )
        progress_path, cache_path = _setup_paths(monkeypatch, tmp_path)

        existing = _make_progress_md(
            [_make_entry("Refactored src/main.py handler")]
        )
        with open(progress_path, "w") as f:
            f.write(existing)

        auto_capture_mod.main()

        with open(progress_path) as f:
            content = f.read()

        assert "## Auto-captured" in content
        assert "src/new_module.py" in content


class TestEmptyDiffNoop:
    def test_empty_diff_produces_no_changes(self, tmp_path, monkeypatch):
        """Empty diff name-status exits silently with no file changes."""
        _setup_git_mocks(monkeypatch)
        monkeypatch.setattr(auto_capture_mod, "get_diff_name_status", lambda: "")
        progress_path, cache_path = _setup_paths(monkeypatch, tmp_path)

        existing = "**Completed**\nOriginal content"
        with open(progress_path, "w") as f:
            f.write(existing)

        auto_capture_mod.main()

        with open(progress_path) as f:
            content = f.read()

        assert content == existing  # unchanged


class TestNonGitRepo:
    def test_non_git_repo_exits_silently(self, tmp_path, monkeypatch):
        """Not inside a git repo exits without crashing."""
        _setup_git_mocks(monkeypatch, in_repo=False)
        progress_path, cache_path = _setup_paths(monkeypatch, tmp_path)

        # Should not raise
        auto_capture_mod.main()

        # No files created
        assert not os.path.exists(progress_path)


class TestNoUncommittedChanges:
    def test_no_uncommitted_changes_exits_silently(self, tmp_path, monkeypatch):
        """No uncommitted changes exits without modifying files."""
        _setup_git_mocks(monkeypatch, has_changes=False)
        progress_path, cache_path = _setup_paths(monkeypatch, tmp_path)

        existing = "**Completed**\nOriginal content"
        with open(progress_path, "w") as f:
            f.write(existing)

        auto_capture_mod.main()

        with open(progress_path) as f:
            content = f.read()

        assert content == existing  # unchanged


class TestMergeAutoCapuredSection:
    def test_merges_into_existing_auto_captured_section(self, tmp_path, monkeypatch):
        """New entries merge into an existing ## Auto-captured section."""
        _setup_git_mocks(monkeypatch)
        _setup_scribe_mocks(
            monkeypatch,
            entries=[_make_entry("Added src/new_file.py", entry_id=None)],
        )
        progress_path, cache_path = _setup_paths(monkeypatch, tmp_path)

        # Build file with existing auto-captured section
        completed = _make_progress_md([_make_entry("Old work on src/utils.py")])
        existing_auto_entry = _make_entry(
            "Modified src/config.py", entry_id="1122334455667788"
        )
        auto_section = "## Auto-captured\n\n" + serialize_entries([existing_auto_entry])
        existing = completed + "\n\n" + auto_section

        with open(progress_path, "w") as f:
            f.write(existing)

        auto_capture_mod.main()

        with open(progress_path) as f:
            content = f.read()

        assert "## Auto-captured" in content
        # Both old and new auto-captured entries present
        assert "src/config.py" in content
        assert "src/new_file.py" in content
        # Only one ## Auto-captured header
        assert content.count("## Auto-captured") == 1


class TestRefCacheUpdate:
    def test_updates_ref_cache_with_initial_score(self, tmp_path, monkeypatch):
        """New entries get score=1 in ref-cache.json."""
        _setup_git_mocks(monkeypatch)
        _setup_scribe_mocks(monkeypatch)
        progress_path, cache_path = _setup_paths(monkeypatch, tmp_path)

        with open(progress_path, "w") as f:
            f.write("")

        auto_capture_mod.main()

        cache = safe_read_json(cache_path)
        assert "scores" in cache
        scores = cache["scores"]
        assert len(scores) == 1
        # All new entries have score=1
        for score in scores.values():
            assert score == 1

    def test_preserves_existing_cache_scores(self, tmp_path, monkeypatch):
        """Existing scores in ref-cache.json are preserved."""
        _setup_git_mocks(monkeypatch)
        _setup_scribe_mocks(monkeypatch)
        progress_path, cache_path = _setup_paths(monkeypatch, tmp_path)

        with open(progress_path, "w") as f:
            f.write("")

        # Pre-populate cache
        existing_cache = {"scores": {"existingid12345678": 5}}
        with open(cache_path, "w") as f:
            json.dump(existing_cache, f)

        auto_capture_mod.main()

        cache = safe_read_json(cache_path)
        scores = cache["scores"]
        assert scores["existingid12345678"] == 5
        # Plus the new entry
        assert len(scores) == 2


class TestUniqueIds:
    def test_generates_unique_16_char_hex_ids(self, tmp_path, monkeypatch):
        """Each entry gets a unique 16-char hex ID."""
        _setup_git_mocks(monkeypatch)

        entries = [
            _make_entry("Added src/a.py", entry_id=None),
            _make_entry("Added src/b.py", entry_id=None),
            _make_entry("Added src/c.py", entry_id=None),
        ]
        _setup_scribe_mocks(monkeypatch, entries=entries)
        # Override parse_name_status and classify_changes to return multiple entries
        monkeypatch.setattr(
            auto_capture_mod,
            "classify_changes",
            lambda ns, st: [
                _make_entry("Added src/a.py", entry_id=None),
                _make_entry("Added src/b.py", entry_id=None),
                _make_entry("Added src/c.py", entry_id=None),
            ],
        )
        progress_path, cache_path = _setup_paths(monkeypatch, tmp_path)

        with open(progress_path, "w") as f:
            f.write("")

        auto_capture_mod.main()

        with open(progress_path) as f:
            content = f.read()

        # Extract IDs from the written content
        import re

        ids = re.findall(r"<!-- id:([0-9a-f]{16}) -->", content)
        assert len(ids) == 3
        # All unique
        assert len(set(ids)) == 3
        # All 16-char hex
        for entry_id in ids:
            assert len(entry_id) == 16
            int(entry_id, 16)  # should not raise


class TestClassifyChangesEmpty:
    def test_no_entries_from_classify_exits(self, tmp_path, monkeypatch):
        """If classify_changes returns empty list, no changes made."""
        _setup_git_mocks(monkeypatch)
        monkeypatch.setattr(auto_capture_mod, "get_diff_name_status", lambda: "M\tsrc/main.py")
        monkeypatch.setattr(auto_capture_mod, "get_diff_stat", lambda: "")
        monkeypatch.setattr(auto_capture_mod, "parse_name_status", lambda o: [("M", "src/main.py", None)])
        monkeypatch.setattr(auto_capture_mod, "classify_changes", lambda ns, st: [])
        progress_path, cache_path = _setup_paths(monkeypatch, tmp_path)

        existing = "**Completed**\nOriginal"
        with open(progress_path, "w") as f:
            f.write(existing)

        auto_capture_mod.main()

        with open(progress_path) as f:
            content = f.read()

        assert content == existing


class TestExceptionSwallowed:
    def test_exception_does_not_crash(self, tmp_path, monkeypatch):
        """Any exception in main() is swallowed silently."""
        _setup_git_mocks(monkeypatch)
        # Force get_diff_name_status to raise
        monkeypatch.setattr(
            auto_capture_mod, "get_diff_name_status", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        progress_path, cache_path = _setup_paths(monkeypatch, tmp_path)

        # Should not raise
        auto_capture_mod.main()


class TestNoExistingFile:
    def test_creates_file_when_none_exists(self, tmp_path, monkeypatch):
        """When session-progress.md doesn't exist, creates it with auto-captured section."""
        _setup_git_mocks(monkeypatch)
        _setup_scribe_mocks(monkeypatch)
        progress_path, cache_path = _setup_paths(monkeypatch, tmp_path)

        # Don't create the file — it doesn't exist yet
        auto_capture_mod.main()

        assert os.path.exists(progress_path)
        with open(progress_path) as f:
            content = f.read()

        assert "## Auto-captured" in content
        assert "src/main.py" in content


class TestDeduplicateHelper:
    def test_extract_filepaths(self):
        """_extract_filepaths pulls path-like tokens from titles."""
        paths = auto_capture_mod._extract_filepaths("Modified src/main.py and utils/helpers.py")
        assert "src/main.py" in paths
        assert "utils/helpers.py" in paths

    def test_extract_filepaths_no_paths(self):
        """_extract_filepaths returns empty for non-path titles."""
        paths = auto_capture_mod._extract_filepaths("General refactoring work")
        assert paths == []

    def test_deduplicate_empty_existing(self):
        """With no existing entries, all new entries are kept."""
        new = [_make_entry("Added src/a.py", entry_id=None)]
        result = auto_capture_mod._deduplicate(new, [])
        assert len(result) == 1

    def test_deduplicate_no_path_in_new_entry_keeps_it(self):
        """New entries without filepaths in title are always kept."""
        new = [_make_entry("General code cleanup", entry_id=None)]
        existing = [_make_entry("Modified src/main.py")]
        result = auto_capture_mod._deduplicate(new, existing)
        assert len(result) == 1

    def test_deduplicate_with_backtick_paths(self):
        """Paths wrapped in backticks are still extracted."""
        paths = auto_capture_mod._extract_filepaths("Updated `src/config.py` settings")
        assert "src/config.py" in paths


class TestGitStatusFailure:
    def test_git_status_nonzero_exits(self, tmp_path, monkeypatch):
        """If git status returns non-zero, exit silently."""
        def mock_run(cmd, **kwargs):
            if cmd[:3] == ["git", "rev-parse", "--is-inside-work-tree"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="true\n", stderr="")
            if cmd[:3] == ["git", "status", "--porcelain"]:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="error")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)
        progress_path, cache_path = _setup_paths(monkeypatch, tmp_path)

        auto_capture_mod.main()
        assert not os.path.exists(cache_path)

"""Tests for hooks.lib.ref_tracker module."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hooks.lib.entries import Entry
from hooks.lib.ref_tracker import (
    TIER1_SCORE,
    TIER2_SCORE,
    TIER3_SCORE,
    extract_context_from_tool_input,
    extract_keywords,
    extract_paths,
    score_entry,
)


class TestExtractPaths:
    def test_finds_paths_with_slash(self) -> None:
        text = "Modified hooks/lib/entries.py for new format"
        paths = extract_paths(text)
        assert "hooks/lib/entries.py" in paths

    def test_finds_multiple_paths(self) -> None:
        text = "Changed src/main.py and tests/test_main.py"
        paths = extract_paths(text)
        assert "src/main.py" in paths
        assert "tests/test_main.py" in paths

    def test_rejects_version_strings(self) -> None:
        text = "Python 3.11.0 is required"
        paths = extract_paths(text)
        assert len(paths) == 0

    def test_rejects_floats(self) -> None:
        text = "The value was 42.5 and 3.14"
        paths = extract_paths(text)
        assert len(paths) == 0

    def test_rejects_bare_filenames(self) -> None:
        text = "Edit the README.md file"
        paths = extract_paths(text)
        assert len(paths) == 0

    def test_finds_backslash_paths(self) -> None:
        text = r"Located at src\lib\utils.py"
        paths = extract_paths(text)
        assert len(paths) == 1

    def test_empty_input(self) -> None:
        assert extract_paths("") == set()

    def test_nested_deep_path(self) -> None:
        text = "File at a/b/c/d/e.txt was updated"
        paths = extract_paths(text)
        assert "a/b/c/d/e.txt" in paths


class TestExtractKeywords:
    def test_filters_stop_words(self) -> None:
        text = "import class function module self none"
        kw = extract_keywords(text)
        assert len(kw) == 0

    def test_filters_short_words(self) -> None:
        text = "a bb ccc"
        kw = extract_keywords(text)
        assert len(kw) == 0

    def test_lowercases(self) -> None:
        text = "Serializer Parser Tokenizer"
        kw = extract_keywords(text)
        assert "serializer" in kw
        assert "parser" in kw
        assert "tokenizer" in kw

    def test_empty_input(self) -> None:
        assert extract_keywords("") == set()

    def test_splits_on_delimiters(self) -> None:
        text = "score=calculate;result,output"
        kw = extract_keywords(text)
        assert "score" in kw
        assert "calculate" in kw
        assert "result" in kw
        assert "output" in kw

    def test_keeps_long_words_not_in_stop_list(self) -> None:
        text = "refactored authentication middleware"
        kw = extract_keywords(text)
        assert "refactored" in kw
        assert "authentication" in kw
        assert "middleware" in kw

    def test_filters_stop_word_with_four_chars(self) -> None:
        # "file", "data", "type", "path" are all stop words with 4+ chars
        text = "file data type path name test args"
        kw = extract_keywords(text)
        assert len(kw) == 0


class TestScoreEntry:
    def _make_entry(
        self, title: str = "", why: str = "", body: str = ""
    ) -> Entry:
        return Entry(type="observation", title=title, why=why, body=body, id=None)

    def test_tier1_exact_path_match(self) -> None:
        entry = self._make_entry(body="Changed hooks/lib/entries.py")
        score = score_entry(entry, {"hooks/lib/entries.py"}, set())
        assert score >= TIER1_SCORE

    def test_tier2_directory_overlap(self) -> None:
        entry = self._make_entry(body="Updated hooks/lib/other.py")
        score = score_entry(entry, {"hooks/lib/entries.py"}, set())
        # Directory hooks/lib matches, but not exact path
        assert score >= TIER2_SCORE

    def test_tier3_keyword_overlap_meets_threshold(self) -> None:
        entry = self._make_entry(
            title="refactored authentication middleware serializer"
        )
        tool_kw = {"refactored", "authentication", "middleware", "serializer"}
        score = score_entry(entry, set(), tool_kw)
        assert score >= TIER3_SCORE

    def test_tier3_below_threshold(self) -> None:
        entry = self._make_entry(title="refactored authentication")
        tool_kw = {"refactored", "authentication"}
        score = score_entry(entry, set(), tool_kw)
        assert score == 0

    def test_all_tiers_combined(self) -> None:
        entry = self._make_entry(
            title="refactored authentication middleware serializer",
            body="Changed hooks/lib/entries.py",
        )
        tool_paths = {"hooks/lib/entries.py"}
        tool_kw = {"refactored", "authentication", "middleware", "serializer"}
        score = score_entry(entry, tool_paths, tool_kw)
        # Tier 1 (2) + Tier 2 (1, same dir) + Tier 3 (1) = 4
        assert score == TIER1_SCORE + TIER2_SCORE + TIER3_SCORE

    def test_no_match_returns_zero(self) -> None:
        entry = self._make_entry(title="unrelated content here")
        score = score_entry(entry, {"some/other/file.py"}, {"completely", "different", "vocabulary", "words"})
        assert score == 0

    def test_uses_title_why_and_body(self) -> None:
        entry = self._make_entry(
            title="hooks/lib/entries.py",
            why="hooks/lib/fileutil.py",
            body="hooks/lib/other.py",
        )
        score = score_entry(entry, {"hooks/lib/entries.py"}, set())
        assert score >= TIER1_SCORE

    def test_tier2_without_tier1(self) -> None:
        # Same directory but different file
        entry = self._make_entry(body="Modified hooks/lib/scoring.py")
        tool_paths = {"hooks/lib/entries.py"}
        score = score_entry(entry, tool_paths, set())
        # Should have Tier 2 but not Tier 1
        assert score == TIER2_SCORE


class TestExtractContextFromToolInput:
    def test_read_payload(self) -> None:
        payload = {
            "tool_input": {"file_path": "/home/user/project/src/main.py"},
            "cwd": "/home/user/project",
        }
        paths, keywords = extract_context_from_tool_input(payload)
        assert "src/main.py" in paths

    def test_edit_payload(self) -> None:
        payload = {
            "tool_input": {
                "file_path": "/home/user/project/src/main.py",
                "old_string": "deprecated_function_call",
                "new_string": "updated_function_call",
            },
            "cwd": "/home/user/project",
        }
        paths, keywords = extract_context_from_tool_input(payload)
        assert "src/main.py" in paths
        assert "deprecated_function_call" in keywords
        assert "updated_function_call" in keywords

    def test_write_payload(self) -> None:
        payload = {
            "tool_input": {"file_path": "/home/user/project/lib/config.json"},
            "cwd": "/home/user/project",
        }
        paths, keywords = extract_context_from_tool_input(payload)
        assert "lib/config.json" in paths

    def test_grep_payload(self) -> None:
        payload = {
            "tool_input": {
                "path": "/home/user/project/src",
                "pattern": "authentication.*handler",
            },
            "cwd": "/home/user/project",
        }
        paths, keywords = extract_context_from_tool_input(payload)
        assert "src" in paths
        assert "authentication" in keywords
        assert "handler" in keywords

    def test_glob_payload_with_response_paths(self) -> None:
        payload = {
            "tool_input": {
                "path": "/home/user/project",
                "pattern": "**/*.py",
            },
            "tool_response": {
                "paths": [
                    "/home/user/project/src/main.py",
                    "/home/user/project/tests/test_main.py",
                ],
            },
            "cwd": "/home/user/project",
        }
        paths, keywords = extract_context_from_tool_input(payload)
        assert "src/main.py" in paths
        assert "tests/test_main.py" in paths

    def test_bash_payload(self) -> None:
        payload = {
            "tool_input": {"command": "pytest tests/test_scoring.py --verbose"},
            "cwd": "/home/user/project",
        }
        paths, keywords = extract_context_from_tool_input(payload)
        assert "pytest" in keywords
        assert "verbose" in keywords

    def test_empty_payload(self) -> None:
        paths, keywords = extract_context_from_tool_input({})
        assert paths == set()
        assert keywords == set()

    def test_malformed_payload(self) -> None:
        payload = {"tool_input": "not a dict", "tool_response": 42}
        paths, keywords = extract_context_from_tool_input(payload)
        assert paths == set()
        assert keywords == set()

    def test_path_normalization_absolute_to_relative(self) -> None:
        payload = {
            "tool_input": {"file_path": "/home/user/project/deep/nested/file.py"},
            "cwd": "/home/user/project",
        }
        paths, keywords = extract_context_from_tool_input(payload)
        assert "deep/nested/file.py" in paths
        # Absolute path should NOT be in the result
        assert "/home/user/project/deep/nested/file.py" not in paths

    def test_relative_path_stays_relative(self) -> None:
        payload = {
            "tool_input": {"file_path": "src/main.py"},
            "cwd": "/home/user/project",
        }
        paths, keywords = extract_context_from_tool_input(payload)
        assert "src/main.py" in paths

    def test_no_cwd_keeps_original_path(self) -> None:
        payload = {
            "tool_input": {"file_path": "/home/user/project/src/main.py"},
        }
        paths, keywords = extract_context_from_tool_input(payload)
        assert "/home/user/project/src/main.py" in paths

    def test_response_paths_normalized(self) -> None:
        payload = {
            "tool_response": {
                "paths": ["/home/user/project/a/b.py"],
            },
            "cwd": "/home/user/project",
        }
        paths, keywords = extract_context_from_tool_input(payload)
        assert "a/b.py" in paths

    def test_response_paths_non_list_ignored(self) -> None:
        payload = {
            "tool_response": {"paths": "not a list"},
            "cwd": "/somewhere",
        }
        paths, keywords = extract_context_from_tool_input(payload)
        assert paths == set()

    def test_response_paths_non_string_items_ignored(self) -> None:
        payload = {
            "tool_response": {"paths": [123, None, "/home/user/project/ok.py"]},
            "cwd": "/home/user/project",
        }
        paths, keywords = extract_context_from_tool_input(payload)
        assert "ok.py" in paths
        assert len(paths) == 1

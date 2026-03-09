"""Tests for hooks.lib.scribe module."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hooks.lib.scribe import (
    _extract_component_name,
    _is_refactor,
    _parse_stat_output,
    classify_changes,
    is_config_file,
    is_test_file,
    parse_name_status,
)


# ---------------------------------------------------------------------------
# parse_name_status
# ---------------------------------------------------------------------------


class TestParseNameStatus:
    def test_added_file(self) -> None:
        output = "A\tsrc/main.py"
        result = parse_name_status(output)
        assert result == [("A", "src/main.py", None)]

    def test_modified_file(self) -> None:
        output = "M\tlib/utils.py"
        result = parse_name_status(output)
        assert result == [("M", "lib/utils.py", None)]

    def test_deleted_file(self) -> None:
        output = "D\told_module.py"
        result = parse_name_status(output)
        assert result == [("D", "old_module.py", None)]

    def test_renamed_file_with_percentage(self) -> None:
        output = "R100\told/path.py\tnew/path.py"
        result = parse_name_status(output)
        assert result == [("R", "old/path.py", "new/path.py")]

    def test_renamed_file_partial_match(self) -> None:
        output = "R085\tutils.py\tlib/utils.py"
        result = parse_name_status(output)
        assert result == [("R", "utils.py", "lib/utils.py")]

    def test_multiple_files(self) -> None:
        output = "A\tnew.py\nM\texisting.py\nD\tremoved.py"
        result = parse_name_status(output)
        assert len(result) == 3
        assert result[0] == ("A", "new.py", None)
        assert result[1] == ("M", "existing.py", None)
        assert result[2] == ("D", "removed.py", None)

    def test_empty_input(self) -> None:
        assert parse_name_status("") == []

    def test_blank_lines_ignored(self) -> None:
        output = "A\ta.py\n\nM\tb.py\n"
        result = parse_name_status(output)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# is_test_file
# ---------------------------------------------------------------------------


class TestIsTestFile:
    def test_test_underscore_prefix(self) -> None:
        assert is_test_file("test_auth.py") is True

    def test_test_dot_prefix(self) -> None:
        assert is_test_file("test.setup.js") is True

    def test_underscore_test_py_suffix(self) -> None:
        assert is_test_file("auth_test.py") is True

    def test_dot_test_ts_suffix(self) -> None:
        assert is_test_file("src/components/Button.test.ts") is True

    def test_dot_test_js_suffix(self) -> None:
        assert is_test_file("utils.test.js") is True

    def test_dot_test_tsx_suffix(self) -> None:
        assert is_test_file("App.test.tsx") is True

    def test_dot_test_jsx_suffix(self) -> None:
        assert is_test_file("Component.test.jsx") is True

    def test_spec_ts_suffix(self) -> None:
        assert is_test_file("service.spec.ts") is True

    def test_spec_js_suffix(self) -> None:
        assert is_test_file("helper.spec.js") is True

    def test_tests_directory(self) -> None:
        assert is_test_file("tests/conftest.py") is True

    def test_dunder_tests_directory(self) -> None:
        assert is_test_file("src/__tests__/utils.js") is True

    def test_non_test_file(self) -> None:
        assert is_test_file("src/auth.py") is False

    def test_non_test_file_with_test_in_name(self) -> None:
        assert is_test_file("src/testimonial.py") is False

    def test_nested_tests_dir(self) -> None:
        assert is_test_file("project/tests/unit/test_core.py") is True


# ---------------------------------------------------------------------------
# is_config_file
# ---------------------------------------------------------------------------


class TestIsConfigFile:
    def test_yml_extension(self) -> None:
        assert is_config_file("config.yml") is True

    def test_yaml_extension(self) -> None:
        assert is_config_file("settings.yaml") is True

    def test_json_extension(self) -> None:
        assert is_config_file("data.json") is True

    def test_toml_extension(self) -> None:
        assert is_config_file("config.toml") is True

    def test_ini_extension(self) -> None:
        assert is_config_file("settings.ini") is True

    def test_cfg_extension(self) -> None:
        assert is_config_file("setup.cfg") is True

    def test_env_extension(self) -> None:
        assert is_config_file(".env") is True

    def test_dockerfile_extension(self) -> None:
        assert is_config_file("app.dockerfile") is True

    def test_pyproject_toml_name(self) -> None:
        assert is_config_file("pyproject.toml") is True

    def test_dockerfile_name(self) -> None:
        assert is_config_file("Dockerfile") is True

    def test_makefile_name(self) -> None:
        assert is_config_file("Makefile") is True

    def test_package_json_name(self) -> None:
        assert is_config_file("package.json") is True

    def test_eslintrc_name(self) -> None:
        assert is_config_file(".eslintrc") is True

    def test_prettierrc_name(self) -> None:
        assert is_config_file(".prettierrc") is True

    def test_editorconfig_name(self) -> None:
        assert is_config_file(".editorconfig") is True

    def test_tsconfig_name(self) -> None:
        assert is_config_file("tsconfig.json") is True

    def test_docker_compose_name(self) -> None:
        assert is_config_file("docker-compose.yml") is True

    def test_procfile_name(self) -> None:
        assert is_config_file("Procfile") is True

    def test_github_workflows_path(self) -> None:
        assert is_config_file(".github/workflows/ci.yml") is True

    def test_gitlab_ci_path(self) -> None:
        assert is_config_file(".gitlab-ci.yml") is True

    def test_circleci_path(self) -> None:
        assert is_config_file(".circleci/config.yml") is True

    def test_non_config_file(self) -> None:
        assert is_config_file("src/main.py") is False

    def test_non_config_ts_file(self) -> None:
        assert is_config_file("src/utils.ts") is False


# ---------------------------------------------------------------------------
# _extract_component_name
# ---------------------------------------------------------------------------


class TestExtractComponentName:
    def test_test_prefix_py(self) -> None:
        assert _extract_component_name("test_auth.py") == "auth"

    def test_test_prefix_nested(self) -> None:
        assert _extract_component_name("tests/test_payments.py") == "payments"

    def test_spec_ts_suffix(self) -> None:
        assert _extract_component_name("payments.spec.ts") == "payments"

    def test_test_ts_suffix(self) -> None:
        assert _extract_component_name("utils.test.ts") == "utils"

    def test_underscore_test_py_suffix(self) -> None:
        assert _extract_component_name("auth_test.py") == "auth"

    def test_test_jsx_suffix(self) -> None:
        assert _extract_component_name("Button.test.jsx") == "Button"

    def test_test_dot_prefix(self) -> None:
        assert _extract_component_name("test.setup.js") == "setup"

    def test_no_recognized_pattern_strips_ext(self) -> None:
        # Not a test file pattern, but _extract_component_name still strips ext
        assert _extract_component_name("plain.py") == "plain"


# ---------------------------------------------------------------------------
# _parse_stat_output / _is_refactor
# ---------------------------------------------------------------------------


class TestParseStatOutput:
    def test_parses_additions_and_deletions(self) -> None:
        stat = " src/main.py | 10 +++++-----\n"
        result = _parse_stat_output(stat)
        assert "src/main.py" in result
        assert result["src/main.py"] == (5, 5)

    def test_additions_only(self) -> None:
        stat = " new_file.py | 8 ++++++++\n"
        result = _parse_stat_output(stat)
        assert result["new_file.py"] == (8, 0)

    def test_deletions_only(self) -> None:
        stat = " old_file.py | 3 ---\n"
        result = _parse_stat_output(stat)
        assert result["old_file.py"] == (0, 3)

    def test_multiple_files(self) -> None:
        stat = " a.py | 4 ++--\n b.py | 6 ++++++\n"
        result = _parse_stat_output(stat)
        assert len(result) == 2
        assert result["a.py"] == (2, 2)
        assert result["b.py"] == (6, 0)

    def test_summary_line_ignored(self) -> None:
        stat = " a.py | 4 ++--\n 1 file changed, 2 insertions(+), 2 deletions(-)\n"
        result = _parse_stat_output(stat)
        assert len(result) == 1

    def test_empty_input(self) -> None:
        assert _parse_stat_output("") == {}


class TestIsRefactor:
    def test_large_deletion_ratio_is_refactor(self) -> None:
        # 3 adds, 7 dels -> dels/total = 0.7 > 0.5
        stat_data = {"file.py": (3, 7)}
        assert _is_refactor("file.py", stat_data) is True

    def test_equal_adds_dels_is_refactor(self) -> None:
        # 5 adds, 5 dels -> dels/total = 0.5, not > 0.5
        stat_data = {"file.py": (5, 5)}
        assert _is_refactor("file.py", stat_data) is False

    def test_mostly_adds_not_refactor(self) -> None:
        # 8 adds, 2 dels -> dels/total = 0.2
        stat_data = {"file.py": (8, 2)}
        assert _is_refactor("file.py", stat_data) is False

    def test_file_not_in_stat_not_refactor(self) -> None:
        assert _is_refactor("missing.py", {}) is False

    def test_zero_changes_not_refactor(self) -> None:
        stat_data = {"file.py": (0, 0)}
        assert _is_refactor("file.py", stat_data) is False


# ---------------------------------------------------------------------------
# classify_changes
# ---------------------------------------------------------------------------


class TestClassifyChanges:
    def test_new_test_file(self) -> None:
        entries = classify_changes(
            [("A", "tests/test_auth.py", None)],
            "",
        )
        assert len(entries) == 1
        assert entries[0].type == "observation"
        assert "Added tests for auth" in entries[0].title
        assert entries[0].id is None

    def test_new_source_file(self) -> None:
        entries = classify_changes(
            [("A", "src/core.py", None)],
            "",
        )
        assert len(entries) == 1
        assert "Created `src/core.py`" in entries[0].title

    def test_new_config_file(self) -> None:
        entries = classify_changes(
            [("A", "pyproject.toml", None)],
            "",
        )
        assert len(entries) == 1
        assert "config" in entries[0].title.lower()
        assert "`pyproject.toml`" in entries[0].title

    def test_deleted_file(self) -> None:
        entries = classify_changes(
            [("D", "old_module.py", None)],
            "",
        )
        assert len(entries) == 1
        assert "Removed" in entries[0].title
        assert "`old_module.py`" in entries[0].title

    def test_renamed_file(self) -> None:
        entries = classify_changes(
            [("R", "old/path.py", "new/path.py")],
            "",
        )
        assert len(entries) == 1
        assert "Moved" in entries[0].title
        assert "`old/path.py`" in entries[0].title
        assert "`new/path.py`" in entries[0].title

    def test_modified_config(self) -> None:
        entries = classify_changes(
            [("M", "package.json", None)],
            "",
        )
        assert len(entries) == 1
        assert "Updated" in entries[0].title
        assert "config" in entries[0].title.lower()

    def test_refactored_file(self) -> None:
        stat = " src/engine.py | 20 ++++++++------------\n"
        entries = classify_changes(
            [("M", "src/engine.py", None)],
            stat,
        )
        assert len(entries) == 1
        assert "Refactored" in entries[0].title

    def test_simple_modification(self) -> None:
        stat = " src/utils.py | 5 ++++-\n"
        entries = classify_changes(
            [("M", "src/utils.py", None)],
            stat,
        )
        assert len(entries) == 1
        assert "Modified" in entries[0].title

    def test_modified_no_stat(self) -> None:
        entries = classify_changes(
            [("M", "src/app.py", None)],
            "",
        )
        assert len(entries) == 1
        assert "Modified" in entries[0].title

    def test_empty_input(self) -> None:
        entries = classify_changes([], "")
        assert entries == []

    def test_all_entries_are_observations(self) -> None:
        entries = classify_changes(
            [
                ("A", "src/new.py", None),
                ("M", "src/old.py", None),
                ("D", "src/dead.py", None),
            ],
            "",
        )
        assert all(e.type == "observation" for e in entries)
        assert all(e.id is None for e in entries)
        assert all(e.why == "" for e in entries)

    def test_unknown_status_code(self) -> None:
        entries = classify_changes(
            [("C", "src/copied.py", None)],
            "",
        )
        assert len(entries) == 1
        assert "Changed" in entries[0].title
        assert "(C)" in entries[0].title

    def test_test_file_body_includes_path(self) -> None:
        entries = classify_changes(
            [("A", "test_scribe.py", None)],
            "",
        )
        assert "test_scribe.py" in entries[0].body

    def test_new_test_with_spec_suffix(self) -> None:
        entries = classify_changes(
            [("A", "src/__tests__/payments.spec.ts", None)],
            "",
        )
        assert "Added tests for payments" in entries[0].title

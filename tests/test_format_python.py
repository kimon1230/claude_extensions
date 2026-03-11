"""Tests for hooks/format-python.sh PostToolUse hook."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

SCRIPT = str(Path(__file__).resolve().parent.parent / "hooks" / "format-python.sh")

# Skip entire module if jq is not available (matches script behavior)
pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None,
    reason="jq not available; script exits immediately without it",
)


def _run_script(stdin_input: str, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    """Run format-python.sh with given stdin and return the result."""
    return subprocess.run(
        ["bash", SCRIPT],
        input=stdin_input,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class TestNonPyFiles:
    """Script should exit 0 immediately for non-.py file paths."""

    def test_txt_file(self) -> None:
        inp = json.dumps({"tool_input": {"file_path": "/tmp/readme.txt"}})
        result = _run_script(inp)
        assert result.returncode == 0

    def test_js_file(self) -> None:
        inp = json.dumps({"tool_input": {"file_path": "/tmp/app.js"}})
        result = _run_script(inp)
        assert result.returncode == 0

    def test_empty_file_path(self) -> None:
        inp = json.dumps({"tool_input": {"file_path": ""}})
        result = _run_script(inp)
        assert result.returncode == 0

    def test_no_extension(self) -> None:
        inp = json.dumps({"tool_input": {"file_path": "/tmp/Makefile"}})
        result = _run_script(inp)
        assert result.returncode == 0


class TestMalformedInput:
    """Script should exit 0 silently on malformed or empty JSON input."""

    def test_empty_stdin(self) -> None:
        result = _run_script("")
        assert result.returncode == 0
        assert result.stderr == ""

    def test_malformed_json(self) -> None:
        result = _run_script("{not valid json!!!")
        assert result.returncode == 0
        assert result.stderr == ""

    def test_missing_tool_input_key(self) -> None:
        inp = json.dumps({"tool_name": "Edit"})
        result = _run_script(inp)
        assert result.returncode == 0
        assert result.stderr == ""

    def test_missing_file_path_key(self) -> None:
        inp = json.dumps({"tool_input": {}})
        result = _run_script(inp)
        assert result.returncode == 0
        assert result.stderr == ""

    def test_null_file_path(self) -> None:
        inp = json.dumps({"tool_input": {"file_path": None}})
        result = _run_script(inp)
        assert result.returncode == 0


class TestNoVenvInRepo:
    """Script should exit 0 when no .venv is found within the repo root."""

    def test_py_file_no_venv(self, tmp_path: Path) -> None:
        """A .py file inside a git repo with no .venv exits 0."""
        # Set up a minimal git repo
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)

        py_file = tmp_path / "src" / "main.py"
        py_file.parent.mkdir(parents=True, exist_ok=True)
        py_file.write_text("x = 1\n")

        inp = json.dumps({"tool_input": {"file_path": str(py_file)}})
        result = _run_script(inp)
        assert result.returncode == 0


class TestOutsideGitRepo:
    """Script should exit 0 (no-op) for files outside any git repo."""

    def test_py_file_outside_git_repo(self) -> None:
        """A .py file outside any git repo is intentionally not formatted."""
        # Create a temp dir that is NOT a git repo
        with tempfile.TemporaryDirectory() as td:
            py_file = Path(td) / "standalone.py"
            py_file.write_text("x=1\n")

            inp = json.dumps({"tool_input": {"file_path": str(py_file)}})
            result = _run_script(inp)
            assert result.returncode == 0

            # File should be unchanged (not formatted)
            assert py_file.read_text() == "x=1\n"


class TestVenvSearchBoundedByRepoRoot:
    """Venv search must not escape the git repo root."""

    def test_venv_above_repo_root_is_ignored(self, tmp_path: Path) -> None:
        """A .venv above the git repo root must not be used."""
        # Structure: tmp_path/.venv/bin/ (decoy), tmp_path/repo/ (git init here)
        decoy_venv = tmp_path / ".venv" / "bin"
        decoy_venv.mkdir(parents=True)

        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)

        py_file = repo / "app.py"
        py_file.write_text("x=1\n")

        inp = json.dumps({"tool_input": {"file_path": str(py_file)}})
        result = _run_script(inp)
        assert result.returncode == 0

        # File should be unchanged — the decoy venv must not have been used
        assert py_file.read_text() == "x=1\n"

    def test_venv_inside_repo_is_found(self, tmp_path: Path) -> None:
        """A .venv inside the git repo root is found (but tools may not exist)."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)

        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)

        py_file = tmp_path / "src" / "module.py"
        py_file.parent.mkdir(parents=True, exist_ok=True)
        py_file.write_text("x = 1\n")

        inp = json.dumps({"tool_input": {"file_path": str(py_file)}})
        result = _run_script(inp)
        # Exits 0 regardless (tools won't exist in the fake venv)
        assert result.returncode == 0


class TestNonexistentPyFile:
    """Script should exit 0 when the .py file doesn't exist on disk."""

    def test_missing_py_file(self) -> None:
        inp = json.dumps({"tool_input": {"file_path": "/tmp/nonexistent_xyz_42.py"}})
        result = _run_script(inp)
        assert result.returncode == 0

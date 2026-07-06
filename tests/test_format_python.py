"""Tests for hooks/format-python.py PostToolUse hook (format_python_mod)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import the module under test eagerly so monkeypatch targets are stable
from hooks import format_python_mod


def _completed(returncode: int = 0, stdout: str = "") -> SimpleNamespace:
    """Minimal stand-in for subprocess.CompletedProcess."""
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


class TestExtractFilePath:
    def test_non_dict_payload(self) -> None:
        assert format_python_mod._extract_file_path(["not", "a", "dict"]) is None

    def test_missing_tool_input(self) -> None:
        assert format_python_mod._extract_file_path({"tool_name": "Edit"}) is None

    def test_tool_input_not_dict(self) -> None:
        assert format_python_mod._extract_file_path({"tool_input": "x"}) is None

    def test_missing_file_path(self) -> None:
        assert format_python_mod._extract_file_path({"tool_input": {}}) is None

    def test_non_string_file_path(self) -> None:
        assert (
            format_python_mod._extract_file_path({"tool_input": {"file_path": None}})
            is None
        )

    def test_valid_file_path(self) -> None:
        payload = {"tool_input": {"file_path": "/tmp/x.py"}}
        assert format_python_mod._extract_file_path(payload) == "/tmp/x.py"


class TestGitRepoRoot:
    def test_success_returns_root(self, monkeypatch) -> None:
        monkeypatch.setattr(
            format_python_mod.subprocess,
            "run",
            lambda *a, **kw: _completed(0, "/repo/root\n"),
        )
        assert format_python_mod._git_repo_root("/repo/root/src") == "/repo/root"

    def test_nonzero_returncode_is_none(self, monkeypatch) -> None:
        monkeypatch.setattr(
            format_python_mod.subprocess, "run", lambda *a, **kw: _completed(128, "")
        )
        assert format_python_mod._git_repo_root("/nowhere") is None

    def test_empty_stdout_is_none(self, monkeypatch) -> None:
        monkeypatch.setattr(
            format_python_mod.subprocess, "run", lambda *a, **kw: _completed(0, "  \n")
        )
        assert format_python_mod._git_repo_root("/nowhere") is None

    def test_exception_is_none(self, monkeypatch) -> None:
        def _boom(*a, **kw):
            raise FileNotFoundError("git not installed")

        monkeypatch.setattr(format_python_mod.subprocess, "run", _boom)
        assert format_python_mod._git_repo_root("/nowhere") is None


class TestFindVenv:
    def test_found_in_start_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".venv").mkdir()
        found = format_python_mod._find_venv(str(tmp_path), str(tmp_path))
        assert found == str(tmp_path / ".venv")

    def test_found_in_ancestor_within_repo(self, tmp_path: Path) -> None:
        (tmp_path / ".venv").mkdir()
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        found = format_python_mod._find_venv(str(sub), str(tmp_path))
        assert found == str(tmp_path / ".venv")

    def test_none_when_no_venv(self, tmp_path: Path) -> None:
        sub = tmp_path / "a"
        sub.mkdir()
        assert format_python_mod._find_venv(str(sub), str(tmp_path)) is None

    def test_decoy_above_repo_root_ignored(self, tmp_path: Path) -> None:
        """A .venv above the repo root must not be returned (CWE-427)."""
        (tmp_path / ".venv").mkdir()  # decoy above repo
        repo = tmp_path / "repo"
        repo.mkdir()
        assert format_python_mod._find_venv(str(repo), str(repo)) is None


class TestRunTool:
    def test_skips_when_tool_missing(self, tmp_path: Path, monkeypatch) -> None:
        calls = []
        monkeypatch.setattr(
            format_python_mod.subprocess, "run", lambda *a, **kw: calls.append(a)
        )
        missing = str(tmp_path / "ruff")  # not created
        format_python_mod._run_tool(missing, ["check"], "/x.py")
        assert calls == []

    def test_runs_when_tool_exists(self, tmp_path: Path, monkeypatch) -> None:
        tool = tmp_path / "ruff"
        tool.write_text("#!/bin/sh\n")
        calls = []
        monkeypatch.setattr(
            format_python_mod.subprocess,
            "run",
            lambda cmd, **kw: calls.append(cmd),
        )
        format_python_mod._run_tool(str(tool), ["check", "--fix"], "/x.py")
        assert calls == [[str(tool), "check", "--fix", "/x.py"]]

    def test_swallows_tool_exception(self, tmp_path: Path, monkeypatch) -> None:
        tool = tmp_path / "black"
        tool.write_text("#!/bin/sh\n")

        def _boom(*a, **kw):
            raise OSError("exec format error")

        monkeypatch.setattr(format_python_mod.subprocess, "run", _boom)
        # Must not raise
        format_python_mod._run_tool(str(tool), ["--quiet"], "/x.py")


class TestFormatFile:
    def test_none_path_noop(self, monkeypatch) -> None:
        monkeypatch.setattr(
            format_python_mod,
            "_git_repo_root",
            lambda *a: pytest.fail("should not reach git"),
        )
        format_python_mod.format_file(None)

    def test_non_py_file_noop(self, monkeypatch) -> None:
        monkeypatch.setattr(
            format_python_mod,
            "_git_repo_root",
            lambda *a: pytest.fail("should not reach git"),
        )
        format_python_mod.format_file("/tmp/readme.txt")

    def test_missing_file_noop(self, monkeypatch) -> None:
        monkeypatch.setattr(
            format_python_mod,
            "_git_repo_root",
            lambda *a: pytest.fail("should not reach git"),
        )
        format_python_mod.format_file("/tmp/does_not_exist_xyz_42.py")

    def test_outside_git_repo_not_formatted(self, tmp_path: Path, monkeypatch) -> None:
        """A .py file outside any git repo is intentionally not formatted (CWE-427)."""
        py_file = tmp_path / "standalone.py"
        py_file.write_text("x=1\n")

        monkeypatch.setattr(format_python_mod, "_git_repo_root", lambda *a: None)
        called = []
        monkeypatch.setattr(
            format_python_mod, "_run_tool", lambda *a: called.append(a)
        )
        format_python_mod.format_file(str(py_file))
        assert called == []

    def test_no_venv_found_noop(self, tmp_path: Path, monkeypatch) -> None:
        py_file = tmp_path / "app.py"
        py_file.write_text("x = 1\n")

        monkeypatch.setattr(
            format_python_mod, "_git_repo_root", lambda *a: str(tmp_path)
        )
        called = []
        monkeypatch.setattr(
            format_python_mod, "_run_tool", lambda *a: called.append(a)
        )
        format_python_mod.format_file(str(py_file))
        assert called == []

    @pytest.mark.skipif(
        sys.platform == "win32", reason="symlink creation needs privileges on Windows"
    )
    def test_symlinked_repo_path_stays_contained(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Editing a file via a symlinked repo path must not pick up a ``.venv``
        above the real repo root (CWE-427): ``realpath`` keeps ``directory``
        aligned with the git-resolved ``repo_root`` so the search stops at the
        repo boundary rather than escaping upward through the symlink."""
        real_repo = tmp_path / "real_repo"
        (real_repo / "src").mkdir(parents=True)
        (real_repo / "src" / "mod.py").write_text("x = 1\n")
        (tmp_path / ".venv").mkdir()  # decoy venv ABOVE the repo root
        link = tmp_path / "link"
        link.symlink_to(real_repo)

        # git resolves symlinks, so repo_root is the real path.
        monkeypatch.setattr(
            format_python_mod, "_git_repo_root", lambda *a: str(real_repo)
        )
        calls = []
        monkeypatch.setattr(
            format_python_mod, "_run_tool", lambda tool, *a: calls.append(tool)
        )
        format_python_mod.format_file(str(link / "src" / "mod.py"))
        # No in-repo .venv exists; the decoy above the repo must never be used.
        assert calls == []

    def test_venv_present_but_no_tools_runs_nothing(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """.venv found but ruff/black binaries absent → subprocess never invoked."""
        (tmp_path / ".venv" / "bin").mkdir(parents=True)
        py_file = tmp_path / "app.py"
        py_file.write_text("x = 1\n")

        monkeypatch.setattr(
            format_python_mod, "_git_repo_root", lambda *a: str(tmp_path)
        )
        calls = []
        monkeypatch.setattr(
            format_python_mod.subprocess, "run", lambda cmd, **kw: calls.append(cmd)
        )
        format_python_mod.format_file(str(py_file))
        assert calls == []

    def test_venv_tools_invoked_ruff_then_black(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The venv ruff and black paths are invoked, ruff first, never bare names."""
        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "ruff").write_text("#!/bin/sh\n")
        (venv_bin / "black").write_text("#!/bin/sh\n")

        py_file = tmp_path / "src" / "module.py"
        py_file.parent.mkdir(parents=True)
        py_file.write_text("x = 1\n")

        monkeypatch.setattr(
            format_python_mod, "_git_repo_root", lambda *a: str(tmp_path)
        )
        calls = []
        monkeypatch.setattr(
            format_python_mod.subprocess, "run", lambda cmd, **kw: calls.append(cmd)
        )
        format_python_mod.format_file(str(py_file))

        assert len(calls) == 2
        ruff_cmd, black_cmd = calls
        assert ruff_cmd[0] == str(venv_bin / "ruff")
        assert ruff_cmd[1:] == ["check", "--fix", "--quiet", str(py_file)]
        assert black_cmd[0] == str(venv_bin / "black")
        assert black_cmd[1:] == ["--quiet", str(py_file)]
        # Never a bare PATH name (CWE-427)
        assert ruff_cmd[0] != "ruff"
        assert black_cmd[0] != "black"

    def test_windows_tool_paths_use_scripts_and_exe(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """On Windows the resolved tool paths use Scripts\\ and .exe (CWE-427)."""
        (tmp_path / ".venv").mkdir()
        py_file = tmp_path / "app.py"
        py_file.write_text("x = 1\n")

        # platformutil uses os.path string ops, so faking os.name is sufficient.
        monkeypatch.setattr(format_python_mod.os, "name", "nt")
        monkeypatch.setattr(
            format_python_mod, "_git_repo_root", lambda *a: str(tmp_path)
        )
        invoked = []
        monkeypatch.setattr(
            format_python_mod,
            "_run_tool",
            lambda tool_path, args, fp: invoked.append((tool_path, args)),
        )
        format_python_mod.format_file(str(py_file))

        assert len(invoked) == 2
        ruff_path, ruff_args = invoked[0]
        black_path, black_args = invoked[1]
        assert "Scripts" in ruff_path and ruff_path.endswith("ruff.exe")
        assert "Scripts" in black_path and black_path.endswith("black.exe")
        assert ruff_args == ["check", "--fix", "--quiet"]
        assert black_args == ["--quiet"]


class TestMain:
    def test_invalid_json_noop(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("{not valid json!!!"))
        monkeypatch.setattr(
            format_python_mod,
            "format_file",
            lambda *a: pytest.fail("should not be called on bad JSON"),
        )
        format_python_mod.main()  # must not raise

    def test_empty_stdin_noop(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        format_python_mod.main()  # must not raise

    def test_valid_json_calls_format_file(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "sys.stdin",
            io.StringIO(json.dumps({"tool_input": {"file_path": "/tmp/x.py"}})),
        )
        seen = []
        monkeypatch.setattr(
            format_python_mod, "format_file", lambda fp: seen.append(fp)
        )
        format_python_mod.main()
        assert seen == ["/tmp/x.py"]

    def test_format_file_exception_swallowed(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "sys.stdin",
            io.StringIO(json.dumps({"tool_input": {"file_path": "/tmp/x.py"}})),
        )

        def _boom(*a, **kw):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(format_python_mod, "format_file", _boom)
        format_python_mod.main()  # must not raise


class TestIntegrationEndToEnd:
    """Drive the real hook process through subprocess to exercise the entry point."""

    ENTRY = str(Path(__file__).resolve().parent.parent / "hooks" / "format-python.py")

    def _run(self, stdin_input: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, self.ENTRY],
            input=stdin_input,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_non_py_file_clean_exit(self) -> None:
        inp = json.dumps({"tool_input": {"file_path": "/tmp/readme.txt"}})
        result = self._run(inp)
        assert result.returncode == 0

    def test_malformed_json_clean_exit(self) -> None:
        result = self._run("{not valid json!!!")
        assert result.returncode == 0

    def test_missing_py_file_clean_exit(self) -> None:
        inp = json.dumps({"tool_input": {"file_path": "/tmp/nonexistent_xyz_42.py"}})
        result = self._run(inp)
        assert result.returncode == 0

    def test_outside_git_repo_not_formatted(self, tmp_path: Path) -> None:
        py_file = tmp_path / "standalone.py"
        py_file.write_text("x=1\n")
        inp = json.dumps({"tool_input": {"file_path": str(py_file)}})
        result = self._run(inp)
        assert result.returncode == 0
        assert py_file.read_text() == "x=1\n"  # unchanged

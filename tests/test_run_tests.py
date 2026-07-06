"""Tests for hooks/run-tests.py Stop hook (run_tests_mod)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import the module under test eagerly so monkeypatch targets are stable
from hooks import run_tests_mod


class _FakeCompleted:
    """Minimal stand-in for subprocess.CompletedProcess."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _make_project(
    tmp_path: Path,
    *,
    marker: str = "pyproject.toml",
    venv_pytest: bool = True,
    tests_dir: str | None = "tests",
) -> Path:
    """Build a fake Python project tree under tmp_path and return its root."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / marker).write_text("")
    if venv_pytest:
        bindir = root / ".venv" / "bin"
        bindir.mkdir(parents=True)
        (bindir / "pytest").write_text("")
    if tests_dir:
        (root / tests_dir).mkdir()
    return root


def _fake_git(
    *, is_repo: bool = True, changed: bool = True, available: bool = True
):
    """Return a subprocess.run replacement handling the git-status probe + pytest.

    Models the single ``git status --porcelain`` call: raises when git is absent,
    returns a non-zero exit for a non-repo, and reports changes via stdout.
    ``pytest_result`` on the returned function object controls the pytest call.
    """

    def run(cmd, *args, **kwargs):
        argv = list(cmd)
        if argv[0] == "git":
            if not available:
                raise FileNotFoundError("git not found")
            if not is_repo:
                return _FakeCompleted(128, stderr="not a git repository")
            return _FakeCompleted(0, stdout="M file.py\n" if changed else "")
        # anything else is the pytest invocation
        return run.pytest_result

    run.pytest_result = _FakeCompleted(0)
    return run


class TestFindProjectRoot:
    def test_finds_root_via_marker(self, tmp_path, monkeypatch):
        root = _make_project(tmp_path)
        sub = root / "a" / "b"
        sub.mkdir(parents=True)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(sub))
        assert run_tests_mod.find_project_root() == str(root)

    def test_uses_cwd_when_env_absent(self, tmp_path, monkeypatch):
        root = _make_project(tmp_path, marker="setup.cfg")
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.chdir(root)
        assert run_tests_mod.find_project_root() == str(root)

    def test_returns_none_when_no_marker(self, tmp_path, monkeypatch):
        bare = tmp_path / "bare"
        bare.mkdir()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(bare))
        assert run_tests_mod.find_project_root() is None


class TestMainNoOp:
    """Branches where main() returns cleanly (exit 0, no output)."""

    def test_no_project_root(self, tmp_path, monkeypatch, capsys):
        bare = tmp_path / "bare"
        bare.mkdir()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(bare))
        run_tests_mod.main()  # must not raise
        assert capsys.readouterr().err == ""

    def test_no_venv_pytest(self, tmp_path, monkeypatch, capsys):
        root = _make_project(tmp_path, venv_pytest=False)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
        run_tests_mod.main()
        assert capsys.readouterr().err == ""

    def test_no_tests_dir(self, tmp_path, monkeypatch, capsys):
        root = _make_project(tmp_path, tests_dir=None)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
        run_tests_mod.main()
        assert capsys.readouterr().err == ""

    def test_test_dir_singular_accepted(self, tmp_path, monkeypatch, capsys):
        root = _make_project(tmp_path, tests_dir="test")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
        calls = []
        base = _fake_git(changed=False)

        def spy(cmd, *a, **kw):
            calls.append(list(cmd))
            return base(cmd, *a, **kw)

        monkeypatch.setattr(subprocess, "run", spy)
        run_tests_mod.main()
        # A singular ``test/`` dir must be accepted, so main reaches the git
        # change-detection probe (rather than short-circuiting on no test dir).
        assert any(c[0] == "git" for c in calls)
        assert capsys.readouterr().err == ""

    def test_git_unavailable(self, tmp_path, monkeypatch, capsys):
        root = _make_project(tmp_path)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
        monkeypatch.setattr(subprocess, "run", _fake_git(available=False))
        run_tests_mod.main()
        assert capsys.readouterr().err == ""

    def test_not_git_repo(self, tmp_path, monkeypatch, capsys):
        root = _make_project(tmp_path)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
        monkeypatch.setattr(subprocess, "run", _fake_git(is_repo=False))
        run_tests_mod.main()
        assert capsys.readouterr().err == ""

    def test_no_changes(self, tmp_path, monkeypatch, capsys):
        root = _make_project(tmp_path)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
        monkeypatch.setattr(subprocess, "run", _fake_git(changed=False))
        run_tests_mod.main()
        assert capsys.readouterr().err == ""


class TestMainRunsPytest:
    def test_changes_and_tests_pass(self, tmp_path, monkeypatch, capsys):
        root = _make_project(tmp_path)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
        fake = _fake_git(changed=True)
        fake.pytest_result = _FakeCompleted(0, stdout="1 passed")
        monkeypatch.setattr(subprocess, "run", fake)
        run_tests_mod.main()  # exit 0, no raise
        assert capsys.readouterr().err == ""

    def test_changes_and_tests_fail(self, tmp_path, monkeypatch, capsys):
        root = _make_project(tmp_path)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
        fake = _fake_git(changed=True)
        fake.pytest_result = _FakeCompleted(
            1, stdout="E   assert False\n1 failed", stderr="tracebk"
        )
        monkeypatch.setattr(subprocess, "run", fake)
        with pytest.raises(SystemExit) as exc:
            run_tests_mod.main()
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "Tests failed:" in err
        assert "1 failed" in err

    def test_pytest_invoked_with_expected_args(self, tmp_path, monkeypatch):
        root = _make_project(tmp_path)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
        captured = {}

        base = _fake_git(changed=True)

        def spy(cmd, *args, **kwargs):
            argv = list(cmd)
            if argv[0] == "git":
                return base(cmd, *args, **kwargs)
            captured["cmd"] = argv
            captured["kwargs"] = kwargs
            return _FakeCompleted(0)

        monkeypatch.setattr(subprocess, "run", spy)
        run_tests_mod.main()
        assert captured["cmd"][1:] == ["--tb=short", "-q", "--no-header", "-x", "."]
        assert captured["cmd"][0].endswith(os.path.join(".venv", "bin", "pytest"))
        assert captured["kwargs"]["cwd"] == str(root)
        assert captured["kwargs"]["encoding"] == "utf-8"
        assert captured["kwargs"]["errors"] == "replace"

    def test_failure_output_tailed_to_50_lines(self, tmp_path, monkeypatch, capsys):
        root = _make_project(tmp_path)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
        fake = _fake_git(changed=True)
        big = "\n".join(f"line{i}" for i in range(200))
        fake.pytest_result = _FakeCompleted(1, stdout=big)
        monkeypatch.setattr(subprocess, "run", fake)
        with pytest.raises(SystemExit):
            run_tests_mod.main()
        err_lines = capsys.readouterr().err.strip().splitlines()
        # "Tests failed:" header + at most 50 tail lines
        assert err_lines[0] == "Tests failed:"
        assert len(err_lines) - 1 == run_tests_mod._TAIL_LINES
        assert err_lines[-1] == "line199"


class TestCrossPlatform:
    def test_windows_pytest_lookup_path(self, tmp_path, monkeypatch):
        """On Windows, pytest is looked up at .venv\\Scripts\\pytest.exe."""
        root = tmp_path / "proj"
        root.mkdir()
        (root / "pyproject.toml").write_text("")
        (root / "tests").mkdir()
        win_bin = root / ".venv" / "Scripts"
        win_bin.mkdir(parents=True)
        (win_bin / "pytest.exe").write_text("")

        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))

        captured = {}
        base = _fake_git(changed=True)

        def spy(cmd, *args, **kwargs):
            argv = list(cmd)
            if argv[0] == "git":
                return base(cmd, *args, **kwargs)
            captured["cmd"] = argv
            return _FakeCompleted(0)

        monkeypatch.setattr(subprocess, "run", spy)
        run_tests_mod.main()
        assert captured["cmd"][0].endswith(
            os.path.join(".venv", "Scripts", "pytest.exe")
        )


class TestNeverCrashes:
    def test_swallows_unexpected_errors(self, tmp_path, monkeypatch):
        root = _make_project(tmp_path)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))

        def boom(*a, **kw):
            raise RuntimeError("forced failure")

        # find_project_root succeeds; blow up inside git handling
        monkeypatch.setattr(subprocess, "run", boom)
        # _has_changes catches OSError/SubprocessError but not RuntimeError;
        # main() must still swallow it.
        run_tests_mod.main()  # must not raise

    def test_systemexit_propagates(self, tmp_path, monkeypatch):
        root = _make_project(tmp_path)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
        fake = _fake_git(changed=True)
        fake.pytest_result = _FakeCompleted(1, stdout="fail")
        monkeypatch.setattr(subprocess, "run", fake)
        with pytest.raises(SystemExit):
            run_tests_mod.main()

    def test_has_changes_swallows_oserror(self, tmp_path, monkeypatch):
        """git absent (OSError on the status probe) -> skip, no crash."""
        root = _make_project(tmp_path)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))

        def raise_os(cmd, *a, **kw):
            if list(cmd)[0] == "git":
                raise OSError("boom")
            return _FakeCompleted(0)

        monkeypatch.setattr(subprocess, "run", raise_os)
        run_tests_mod.main()  # _has_changes swallows OSError -> False -> return

    def test_has_changes_swallows_subprocess_error(self, tmp_path, monkeypatch):
        """A SubprocessError on the status probe -> treated as no changes."""
        root = _make_project(tmp_path)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))

        def raise_sub(cmd, *a, **kw):
            if list(cmd)[0] == "git":
                raise subprocess.SubprocessError("boom")
            return _FakeCompleted(0)

        monkeypatch.setattr(subprocess, "run", raise_sub)
        run_tests_mod.main()  # status probe errors -> return, no crash

    def test_git_status_decodes_utf8_replace(self, tmp_path, monkeypatch):
        """The change-detection git call is invoked with encoding='utf-8',
        errors='replace' so real non-ASCII filenames would decode safely instead
        of raising UnicodeDecodeError (which escapes the caught set and silently
        skips the run). Asserts the decode-safe kwargs are passed."""
        root = _make_project(tmp_path)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
        captured = {}

        def spy(cmd, *a, **kw):
            argv = list(cmd)
            if argv[0] == "git" and "status" in argv:
                captured["kwargs"] = kw
                return _FakeCompleted(0, stdout="")
            return _FakeCompleted(0)

        monkeypatch.setattr(subprocess, "run", spy)
        run_tests_mod.main()
        assert captured["kwargs"]["encoding"] == "utf-8"
        assert captured["kwargs"]["errors"] == "replace"

"""Tests for hooks.lib.paths — project name resolution and status paths."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hooks.lib.paths import (
    get_project_name,
    get_ref_cache_path,
    get_session_progress_path,
    get_status_dir,
)


def _make_subprocess_side_effect(results: dict[str, subprocess.CompletedProcess]):
    """Build a side-effect function for monkeypatching subprocess.run.

    ``results`` maps a command tuple key to its CompletedProcess.
    Commands not in the map raise CalledProcessError.
    """

    def _side_effect(cmd, **_kwargs):
        key = tuple(cmd)
        if key in results:
            result = results[key]
            if isinstance(result, Exception):
                raise result
            return result
        raise subprocess.CalledProcessError(1, cmd)

    return _side_effect


class TestGetProjectNameFromRemote:
    def test_ssh_url(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            _make_subprocess_side_effect(
                {
                    ("git", "remote", "get-url", "origin"): subprocess.CompletedProcess(
                        [], 0, stdout="git@github.com:user/my-lib.git\n", stderr=""
                    ),
                }
            ),
        )
        assert get_project_name() == "my-lib"

    def test_https_url_with_git_suffix(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            _make_subprocess_side_effect(
                {
                    ("git", "remote", "get-url", "origin"): subprocess.CompletedProcess(
                        [], 0, stdout="https://github.com/user/my-lib.git\n", stderr=""
                    ),
                }
            ),
        )
        assert get_project_name() == "my-lib"

    def test_https_url_without_git_suffix(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            _make_subprocess_side_effect(
                {
                    ("git", "remote", "get-url", "origin"): subprocess.CompletedProcess(
                        [], 0, stdout="https://github.com/user/my-lib\n", stderr=""
                    ),
                }
            ),
        )
        assert get_project_name() == "my-lib"


class TestGetProjectNameFallbackToGitRoot:
    def test_falls_back_to_git_root_basename(self, monkeypatch):
        def _side_effect(cmd, **_kwargs):
            key = tuple(cmd)
            if key == ("git", "remote", "get-url", "origin"):
                raise subprocess.CalledProcessError(1, cmd)
            if key == ("git", "rev-parse", "--show-toplevel"):
                return subprocess.CompletedProcess(
                    [], 0, stdout="/home/user/projects/cool-project\n", stderr=""
                )
            raise subprocess.CalledProcessError(1, cmd)

        monkeypatch.setattr(subprocess, "run", _side_effect)
        assert get_project_name() == "cool-project"


class TestGetProjectNameFallbackToCwd:
    def test_falls_back_to_cwd_basename(self, monkeypatch):
        def _side_effect(cmd, **_kwargs):
            raise subprocess.CalledProcessError(1, cmd)

        monkeypatch.setattr(subprocess, "run", _side_effect)
        monkeypatch.setattr(os, "getcwd", lambda: "/tmp/my-workspace")
        assert get_project_name() == "my-workspace"


class TestGetProjectNameGitNotInstalled:
    def test_git_not_found_falls_to_cwd(self, monkeypatch):
        def _side_effect(cmd, **_kwargs):
            raise FileNotFoundError("git not found")

        monkeypatch.setattr(subprocess, "run", _side_effect)
        monkeypatch.setattr(os, "getcwd", lambda: "/home/dev/fallback-repo")
        assert get_project_name() == "fallback-repo"


class TestGetStatusDir:
    def test_returns_correct_path_and_creates_directory(self, tmp_path, monkeypatch):
        fake_home = str(tmp_path / "fakehome")
        monkeypatch.setenv("HOME", fake_home)
        # expanduser reads HOME env var
        monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", fake_home))

        result = get_status_dir("test-project")

        expected = os.path.join(fake_home, ".claude", "status", "test-project")
        assert result == expected
        assert os.path.isdir(expected)

    def test_uses_get_project_name_when_none(self, tmp_path, monkeypatch):
        fake_home = str(tmp_path / "fakehome")
        monkeypatch.setenv("HOME", fake_home)
        monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", fake_home))

        # Mock subprocess to return a known project name
        monkeypatch.setattr(
            subprocess,
            "run",
            _make_subprocess_side_effect(
                {
                    ("git", "remote", "get-url", "origin"): subprocess.CompletedProcess(
                        [], 0, stdout="git@github.com:org/auto-name.git\n", stderr=""
                    ),
                }
            ),
        )

        result = get_status_dir()
        expected = os.path.join(fake_home, ".claude", "status", "auto-name")
        assert result == expected
        assert os.path.isdir(expected)

    def test_idempotent_on_existing_directory(self, tmp_path, monkeypatch):
        fake_home = str(tmp_path / "fakehome")
        monkeypatch.setenv("HOME", fake_home)
        monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", fake_home))

        # Call twice — second call should not raise
        get_status_dir("idempotent-proj")
        result = get_status_dir("idempotent-proj")
        assert os.path.isdir(result)


class TestGetSessionProgressPath:
    def test_returns_correct_path(self, tmp_path, monkeypatch):
        fake_home = str(tmp_path / "fakehome")
        monkeypatch.setenv("HOME", fake_home)
        monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", fake_home))

        result = get_session_progress_path("my-proj")
        expected = os.path.join(
            fake_home, ".claude", "status", "my-proj", "session-progress.md"
        )
        assert result == expected


class TestGetRefCachePath:
    def test_returns_correct_path(self, tmp_path, monkeypatch):
        fake_home = str(tmp_path / "fakehome")
        monkeypatch.setenv("HOME", fake_home)
        monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", fake_home))

        result = get_ref_cache_path("my-proj")
        expected = os.path.join(
            fake_home, ".claude", "status", "my-proj", "ref-cache.json"
        )
        assert result == expected

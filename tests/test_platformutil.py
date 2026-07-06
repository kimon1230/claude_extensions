"""Tests for hooks.lib.platformutil — cross-platform venv/path helpers.

The Windows branches are exercised on this POSIX host by monkeypatching
``os.name`` to ``"nt"`` (the helpers use string ops, so this works cross-host).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hooks.lib.platformutil import venv_bin_dir, venv_tool, walk_up


class TestVenvBinDir:
    def test_posix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "posix")
        assert venv_bin_dir("/proj/.venv") == os.path.join("/proj/.venv", "bin")

    def test_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "nt")
        assert venv_bin_dir("/proj/.venv") == os.path.join("/proj/.venv", "Scripts")


class TestVenvTool:
    def test_posix_no_suffix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "posix")
        assert venv_tool("/proj/.venv", "ruff") == os.path.join(
            "/proj/.venv", "bin", "ruff"
        )

    def test_windows_exe_suffix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "nt")
        assert venv_tool("/proj/.venv", "pytest") == os.path.join(
            "/proj/.venv", "Scripts", "pytest.exe"
        )

    def test_windows_appends_exactly_one_suffix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(os, "name", "nt")
        assert os.path.basename(venv_tool("/v", "black")) == "black.exe"

    def test_posix_bare_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "posix")
        assert os.path.basename(venv_tool("/v", "black")) == "black"


class TestWalkUp:
    def test_yields_start_first(self, tmp_path: Path) -> None:
        chain = list(walk_up(str(tmp_path)))
        assert chain[0] == os.path.abspath(str(tmp_path))

    def test_reaches_and_stops_at_root(self, tmp_path: Path) -> None:
        chain = list(walk_up(str(tmp_path)))
        # Terminates (no infinite loop); the last element is its own parent.
        assert chain[-1] == os.path.dirname(chain[-1])
        assert chain[-1] == tmp_path.anchor

    def test_includes_all_intermediate_dirs(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        chain = list(walk_up(str(deep)))
        for expected in (deep, deep.parent, deep.parent.parent, tmp_path):
            assert os.path.abspath(str(expected)) in chain

    def test_relative_path_is_absolutized(self) -> None:
        chain = list(walk_up("."))
        assert chain[0] == os.getcwd()

    def test_root_terminates_with_single_yield(self) -> None:
        anchor = Path.cwd().anchor  # "/" on POSIX
        chain = list(walk_up(anchor))
        assert len(chain) == 1

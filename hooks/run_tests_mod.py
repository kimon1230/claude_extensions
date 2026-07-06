"""Importable logic for run-tests.py (hyphenated name can't be imported directly).

Stop hook: run pytest when Claude finishes responding. Only runs in a Python
project with a test suite where files actually changed.

Exit codes: 0 = do nothing / success; 1 = non-blocking warning (Claude does NOT
see it — no loop risk). NEVER exit 2 (that blocks and risks a loop). The hook
must never crash — all unexpected errors are swallowed and treated as exit 0.
"""

from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.platformutil import venv_tool, walk_up

# Marker files that identify a Python project root.
_ROOT_MARKERS = ("pyproject.toml", "setup.py", "setup.cfg")

# Number of trailing output lines to surface on failure.
_TAIL_LINES = 50


def find_project_root() -> str | None:
    """Return the nearest ancestor containing a Python project marker, else None.

    Starts at ``CLAUDE_PROJECT_DIR`` (or the cwd) and walks up to the filesystem
    root, looking for ``pyproject.toml``/``setup.py``/``setup.cfg``.
    """
    start = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    for directory in walk_up(start):
        for marker in _ROOT_MARKERS:
            if os.path.isfile(os.path.join(directory, marker)):
                return directory
    return None


def _has_changes(root: str) -> bool:
    """Return True if ``root`` is a git work tree with uncommitted changes.

    A single ``git status --porcelain`` both detects the work tree (non-zero
    exit when ``root`` is not a repo; ``OSError`` when git is absent) and reports
    staged, unstaged, and untracked changes (non-empty output) — the default
    ``-unormal`` already lists an untracked dir as ``?? dir/``, which is enough
    for the boolean check without walking every file inside it. Decodes as UTF-8
    with ``errors="replace"`` so a non-ASCII changed filename can never raise
    ``UnicodeDecodeError`` and silently skip the run.
    """
    try:
        result = subprocess.run(
            ["git", "-C", root, "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


def main() -> None:
    """Run the project test suite and warn (exit 1) on failure; never block.

    Silently returns (exit 0) unless: a Python project root with a ``.venv``
    pytest and a ``tests``/``test`` directory is found, the project is a git repo
    with changes, and pytest then exits non-zero.
    """
    try:
        root = find_project_root()
        if root is None:
            return

        # pytest in venv only — never PATH (CWE-427).
        pytest = venv_tool(os.path.join(root, ".venv"), "pytest")
        if not os.path.isfile(pytest):
            return

        if not (
            os.path.isdir(os.path.join(root, "tests"))
            or os.path.isdir(os.path.join(root, "test"))
        ):
            return

        # Skip unless this is a git work tree with changes. One probe covers
        # all three "do nothing" cases: git absent, not a repo, clean tree.
        if not _has_changes(root):
            return

        result = subprocess.run(
            [pytest, "--tb=short", "-q", "--no-header", "-x", "."],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            output = (result.stdout or "") + (result.stderr or "")
            tail = "\n".join(output.splitlines()[-_TAIL_LINES:])
            print("Tests failed:", file=sys.stderr)
            print(tail, file=sys.stderr)
            sys.exit(1)
    except SystemExit:
        raise
    except Exception:
        # Never crash the Stop hook; treat unexpected errors as a no-op.
        return

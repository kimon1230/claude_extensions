"""Core logic for the format-python PostToolUse hook.

Cross-platform port of the original ``format-python.sh``. After an Edit/Write on
a ``.py`` file, format it with the project's own venv tools: ``ruff --fix`` first
(may add/remove imports) then ``black`` (final formatting).

Security (CWE-427): tools are resolved **only** from a ``.venv`` inside the git
repository containing the file. Files outside a git repo are never formatted, the
venv search never escapes above the repo root, and there is no PATH fallback — so
an attacker-planted ``ruff``/``black`` elsewhere can never be executed.

Uses ``os.path`` (string) operations to stay consistent with ``lib.platformutil``
and to keep the Windows path branch unit-testable on a POSIX host. Stdlib only.
Must NEVER crash — every entry point swallows errors and exits cleanly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.platformutil import venv_tool, walk_up


def _git_repo_root(directory: str) -> str | None:
    """Return the git repo root containing ``directory``, or ``None``.

    Wraps ``git -C <dir> rev-parse --show-toplevel``. Returns ``None`` when the
    directory is outside any git repo, git is absent, or the call fails — the
    caller treats that as "do not format" (CWE-427).
    """
    try:
        result = subprocess.run(
            ["git", "-C", directory, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return root or None


def _find_venv(directory: str, repo_root: str) -> str | None:
    """Search for a ``.venv`` from ``directory`` up to (and including) ``repo_root``.

    Walks upward, returning the first directory that contains a ``.venv``
    subdirectory. The search stops once ``repo_root`` is examined and never
    ascends above it (CWE-427). Returns the ``.venv`` path, or ``None``.

    Both ``directory`` and ``repo_root`` must already be real paths (symlinks
    resolved) so the ``current == repo_root`` boundary check fires reliably —
    ``format_file`` guarantees this via ``os.path.realpath``.
    """
    for current in walk_up(directory):
        candidate = os.path.join(current, ".venv")
        if os.path.isdir(candidate):
            return candidate
        if current == repo_root:
            break
    return None


def _run_tool(tool_path: str, args: list[str], file_path: str) -> None:
    """Run a resolved venv tool on ``file_path``, ignoring any failure.

    Only executes when ``tool_path`` is an existing file — never falls back to a
    PATH lookup (CWE-427). Mirrors the shell ``2>/dev/null``: tool errors are
    discarded and never propagated.
    """
    if not os.path.isfile(tool_path):
        return
    try:
        subprocess.run(
            [tool_path, *args, file_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        pass


def format_file(file_path: str | None) -> None:
    """Format ``file_path`` with the project's venv ``ruff`` then ``black``.

    No-ops (returns silently) when: the path is missing/not a ``.py`` file, the
    file does not exist, it lives outside a git repo, or no ``.venv`` is found
    within the repo. Never raises.
    """
    if not file_path or not file_path.endswith(".py"):
        return
    if not os.path.isfile(file_path):
        return

    # realpath (not abspath) so a symlinked repo path still matches the
    # git-resolved repo_root below; otherwise the _find_venv break never fires
    # and the search could escape above the repo root (CWE-427).
    directory = os.path.dirname(os.path.realpath(file_path))

    repo_root = _git_repo_root(directory)
    if repo_root is None:
        return
    repo_root = os.path.realpath(repo_root)

    venv_root = _find_venv(directory, repo_root)
    if venv_root is None:
        return

    # Ruff fix first (may restructure imports), then black for final formatting.
    _run_tool(venv_tool(venv_root, "ruff"), ["check", "--fix", "--quiet"], file_path)
    _run_tool(venv_tool(venv_root, "black"), ["--quiet"], file_path)


def _extract_file_path(data: object) -> str | None:
    """Pull ``tool_input.file_path`` from a parsed hook payload, or ``None``."""
    if not isinstance(data, dict):
        return None
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    file_path = tool_input.get("file_path")
    if isinstance(file_path, str):
        return file_path
    return None


def main() -> None:
    """Read the hook JSON from stdin and format the referenced file.

    Silent on every error (missing/invalid JSON, unreadable stdin, tool
    failures) so the hook never disrupts the Edit/Write it follows.
    """
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    try:
        format_file(_extract_file_path(data))
    except Exception:
        pass

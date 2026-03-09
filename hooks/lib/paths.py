"""Project name and status path resolution.

Determines the current project name from git metadata or cwd,
and resolves paths under ``~/.claude/status/<project-name>/``.
Stdlib only — no external dependencies.
"""

from __future__ import annotations

import os
import subprocess


def get_project_name() -> str:
    """Determine project name with fallback precedence.

    1. Git remote ``origin`` URL — parse last path component, strip ``.git``.
    2. Git repo root directory basename.
    3. Current working directory basename.
    """
    # Try git remote origin
    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if url:
            # Handle both SSH (git@host:user/repo.git) and HTTPS URLs
            # SSH: git@github.com:user/my-lib.git → my-lib
            # HTTPS: https://github.com/user/my-lib.git → my-lib
            last_component = url.rstrip("/").rsplit("/", 1)[-1]
            # Also handle SSH colon-separated paths
            last_component = last_component.rsplit(":", 1)[-1]
            if last_component.endswith(".git"):
                last_component = last_component[:-4]
            if last_component:
                return last_component
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Try git repo root basename
    try:
        toplevel = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if toplevel:
            name = os.path.basename(toplevel)
            if name:
                return name
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Fall back to cwd basename
    return os.path.basename(os.getcwd())


def get_status_dir(project_name: str | None = None) -> str:
    """Return ``~/.claude/status/<project-name>/``, creating it if needed."""
    if project_name is None:
        project_name = get_project_name()
    # Sanitize: strip path separators and '..' to prevent traversal (CWE-22)
    project_name = os.path.basename(project_name.replace("..", ""))
    if not project_name:
        project_name = "unknown"
    path = os.path.join(os.path.expanduser("~"), ".claude", "status", project_name)
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def get_session_progress_path(project_name: str | None = None) -> str:
    """Return path to ``session-progress.md`` inside the status directory."""
    return os.path.join(get_status_dir(project_name), "session-progress.md")


def get_ref_cache_path(project_name: str | None = None) -> str:
    """Return path to ``ref-cache.json`` inside the status directory."""
    return os.path.join(get_status_dir(project_name), "ref-cache.json")

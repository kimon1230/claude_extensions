"""Cross-platform path and virtualenv helpers for hook scripts.

Small primitives shared by the ``format-python`` and ``run-tests`` hooks so the
Windows (``.venv\\Scripts\\*.exe``) vs POSIX (``.venv/bin/*``) layout difference
lives in one tested place.

Uses ``os.path`` (string) operations rather than ``pathlib`` on purpose:
``pathlib.Path`` binds to the host OS and cannot instantiate the other platform's
path type, whereas string ops let the Windows branch be unit-tested on a POSIX CI
host by monkeypatching ``os.name``. Stdlib only.
"""

from __future__ import annotations

import os
from collections.abc import Iterator


def venv_bin_dir(venv_root: str) -> str:
    """Return a venv's executable directory: ``Scripts`` on Windows, else ``bin``."""
    return os.path.join(venv_root, "Scripts" if os.name == "nt" else "bin")


def venv_tool(venv_root: str, name: str) -> str:
    """Return the path to a venv tool, adding the ``.exe`` suffix on Windows.

    ``name`` is the bare tool name (e.g. ``"ruff"``, ``"pytest"``); the caller is
    responsible for checking whether the returned path actually exists.
    """
    exe = f"{name}.exe" if os.name == "nt" else name
    return os.path.join(venv_bin_dir(venv_root), exe)


def walk_up(start: str) -> Iterator[str]:
    """Yield ``start`` and each ancestor up to the filesystem root (inclusive).

    Termination is via ``current == dirname(current)`` — true for the POSIX root
    ``"/"`` and for Windows drive roots (``"C:\\"``), so it never loops forever.
    A comparison against the literal ``"/"`` would loop forever on Windows.
    """
    current = os.path.abspath(start)
    while True:
        yield current
        parent = os.path.dirname(current)
        if parent == current:
            return
        current = parent

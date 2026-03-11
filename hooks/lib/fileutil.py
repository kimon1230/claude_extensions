"""Shared file utilities for safe I/O operations.

Provides atomic writes and safe JSON read/write with backup support.
Stdlib only — no external dependencies.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile


def atomic_write(path: str, content: str) -> None:
    """Write content to path atomically via tempfile + os.replace.

    Creates parent directories if they don't exist. A crash mid-write
    never corrupts the target file.
    """
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, mode=0o700, exist_ok=True)
        os.chmod(parent, 0o700)

    fd, tmp_path = tempfile.mkstemp(dir=parent or ".")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except BaseException:
        # Clean up tempfile on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def safe_read_json(path: str, backup_path: str | None = None) -> dict:
    """Read and parse JSON from path with graceful fallbacks.

    Returns empty dict on missing file, empty file, or corrupt JSON.
    On corrupt JSON, logs a warning to stderr and optionally tries
    a backup file.
    """
    try:
        with open(path) as f:
            raw = f.read()
    except FileNotFoundError:
        return {}

    if not raw:
        return {}

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"Warning: corrupt JSON at {os.path.basename(path)}", file=sys.stderr)

        if backup_path is not None:
            try:
                with open(backup_path) as f:
                    backup_raw = f.read()
                if backup_raw:
                    return json.loads(backup_raw)
            except (FileNotFoundError, json.JSONDecodeError):
                pass

        return {}


def safe_write_json(path: str, data: dict) -> None:
    """Write data as formatted JSON, backing up any existing file first.

    If path already exists, copies it to path + ".bak" before writing.
    Uses atomic_write for crash safety. Creates parent directories if needed.
    """
    if os.path.exists(path):
        backup_path = path + ".bak"
        parent = os.path.dirname(backup_path)
        if parent:
            os.makedirs(parent, mode=0o700, exist_ok=True)
            os.chmod(parent, 0o700)
        shutil.copy2(path, backup_path)
        os.chmod(backup_path, 0o600)

    content = json.dumps(data, indent=2)
    atomic_write(path, content)

"""Git diff classification module for auto-generating observation entries.

Parses git diff output, classifies file changes, and produces Entry objects.
Stdlib only — no external dependencies.
"""

from __future__ import annotations

import os
import re
import subprocess

from lib.entries import Entry

# Suffixes and patterns for test file detection
_TEST_SUFFIXES = (
    "_test.py",
    ".test.ts",
    ".test.js",
    ".test.tsx",
    ".test.jsx",
    ".spec.ts",
    ".spec.js",
)

# Extensions for config file detection (including leading dot)
_CONFIG_EXTENSIONS = frozenset(
    {".yml", ".yaml", ".json", ".toml", ".ini", ".cfg", ".env", ".dockerfile"}
)

# Exact filenames (case-sensitive) for config file detection
_CONFIG_NAMES = frozenset(
    {
        "Dockerfile",
        "docker-compose.yml",
        "Makefile",
        "Procfile",
        ".eslintrc",
        ".prettierrc",
        ".editorconfig",
        "tsconfig.json",
        "package.json",
        "pyproject.toml",
        "setup.cfg",
    }
)

# Directory patterns indicating CI config
_CI_PATTERNS = (".github/workflows/", ".gitlab-ci", ".circleci/")

# Pattern for git diff --stat lines: ` path | 10 +++++-----`
_STAT_LINE_RE = re.compile(r"^\s*(.+?)\s*\|\s*\d+\s*(\+*)(-*)\s*$")


def parse_name_status(output: str) -> list[tuple[str, str, str | None]]:
    """Parse ``git diff --name-status`` output.

    Returns list of ``(status, filepath, renamed_to)``.
    For renames, ``renamed_to`` is the new path; for others it is ``None``.
    """
    results: list[tuple[str, str, str | None]] = []
    for line in output.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status_code = parts[0]
        if status_code.startswith("R"):
            old_path = parts[1] if len(parts) > 1 else ""
            new_path = parts[2] if len(parts) > 2 else ""
            results.append(("R", old_path, new_path))
        else:
            filepath = parts[1] if len(parts) > 1 else ""
            results.append((status_code, filepath, None))
    return results


def is_test_file(filepath: str) -> bool:
    """Return True if the file is a test file."""
    basename = os.path.basename(filepath)
    if basename.startswith("test_") or basename.startswith("test."):
        return True
    if any(basename.endswith(suffix) for suffix in _TEST_SUFFIXES):
        return True
    dirs = filepath.replace("\\", "/").split("/")
    return "tests" in dirs or "__tests__" in dirs


def _get_extension(filepath: str) -> str:
    """Get file extension, handling dotfiles like ``.env`` correctly."""
    basename = os.path.basename(filepath)
    _, ext = os.path.splitext(basename)
    if ext:
        return ext.lower()
    # For dotfiles with no extension (e.g. ".env"), treat basename as extension
    if basename.startswith("."):
        return basename.lower()
    return ""


def is_config_file(filepath: str) -> bool:
    """Return True if the file is a config/infra file."""
    basename = os.path.basename(filepath)
    ext = _get_extension(filepath)
    if ext in _CONFIG_EXTENSIONS:
        return True
    if basename in _CONFIG_NAMES:
        return True
    normalized = filepath.replace("\\", "/")
    return any(pattern in normalized for pattern in _CI_PATTERNS)


def _extract_component_name(filepath: str) -> str:
    """Extract component name from a test file path.

    ``test_auth.py`` -> ``auth``, ``test_payments.spec.ts`` -> ``payments``.
    """
    basename = os.path.basename(filepath)
    name = basename
    if name.startswith("test_"):
        name = name[5:]
    elif name.startswith("test."):
        name = name[5:]

    for suffix in _TEST_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    else:
        name, _ = os.path.splitext(name)

    return name if name else basename


def _parse_stat_output(stat_output: str) -> dict[str, tuple[int, int]]:
    """Parse ``git diff --stat`` output into per-file add/delete counts.

    Returns dict mapping filepath to ``(additions, deletions)``.
    """
    result: dict[str, tuple[int, int]] = {}
    for line in stat_output.strip().splitlines():
        m = _STAT_LINE_RE.match(line)
        if m:
            path = m.group(1).strip()
            adds = len(m.group(2))
            dels = len(m.group(3))
            result[path] = (adds, dels)
    return result


def _is_refactor(filepath: str, stat_data: dict[str, tuple[int, int]]) -> bool:
    """Return True if a modified file has large changes (>50% changed).

    Uses git diff --stat ``+`` and ``-`` counts. When deletions make up
    more than 50% of total changes, the file was substantially rewritten.
    """
    if filepath not in stat_data:
        return False
    adds, dels = stat_data[filepath]
    total = adds + dels
    if total == 0:
        return False
    return dels / total > 0.5


def classify_changes(
    name_status_entries: list[tuple[str, str, str | None]],
    stat_output: str,
) -> list[Entry]:
    """Classify each file change into an observation Entry.

    Returns list of Entry objects with ``id=None``.
    """
    stat_data = _parse_stat_output(stat_output)
    entries: list[Entry] = []

    for status, filepath, renamed_to in name_status_entries:
        body = ""
        if status == "A":
            if is_test_file(filepath):
                component = _extract_component_name(filepath)
                title = f"Added tests for {component}"
                body = f"New test file `{filepath}`."
            elif is_config_file(filepath):
                title = f"Added `{filepath}` config"
            else:
                title = f"Created `{filepath}`"
        elif status == "D":
            title = f"Removed `{filepath}`"
        elif status == "R":
            title = f"Moved `{filepath}` \u2192 `{renamed_to}`"
        elif status == "M":
            if is_config_file(filepath):
                title = f"Updated `{filepath}` config"
            elif _is_refactor(filepath, stat_data):
                title = f"Refactored `{filepath}`"
            else:
                title = f"Modified `{filepath}`"
        else:
            title = f"Changed `{filepath}` ({status})"

        entries.append(
            Entry(type="observation", title=title, why="", body=body, id=None)
        )

    return entries


def get_diff_name_status() -> str:
    """Run ``git diff --name-status`` for both staged and unstaged changes.

    Timeout 5s. Returns empty string on failure.
    """
    lines: list[str] = []
    for cmd in (
        ["git", "diff", "--name-status", "HEAD"],
        ["git", "diff", "--name-status", "--cached"],
    ):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                lines.append(result.stdout.strip())
        except (subprocess.TimeoutExpired, OSError):
            pass
    return "\n".join(lines)


def get_diff_stat() -> str:
    """Run ``git diff --stat HEAD``, timeout 5s. Return empty string on failure."""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout
    except (subprocess.TimeoutExpired, OSError):
        pass
    return ""

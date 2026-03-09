"""Scoring logic for matching entries against tool context.

Scores entries based on file path overlap, directory overlap, and keyword
similarity with tool inputs/outputs. Stdlib only.
"""

from __future__ import annotations

import os
import re

from lib.entries import Entry

STOP_WORDS = frozenset({
    "file", "data", "type", "config", "error", "return", "import", "class",
    "function", "module", "self", "none", "true", "false", "test", "args",
    "kwargs", "init", "main", "name", "path", "value", "list", "dict", "string",
})

TIER1_SCORE = 2  # Exact file path match
TIER2_SCORE = 1  # Directory overlap
TIER3_SCORE = 1  # Keyword overlap
TIER3_MIN_KEYWORDS = 3  # Minimum shared keywords for Tier 3
MIN_KEYWORD_LEN = 4  # Minimum keyword length

# Pattern: requires at least one / or \ (avoids matching "3.11.0", floats, URLs)
_PATH_RE = re.compile(r"(?:[\w\-]+[/\\])+[\w\-]+\.[\w]+", re.ASCII)

_SPLIT_RE = re.compile(r"[\s,;:=\(\)\[\]\{\}\"\'`<>|&.*?+\-/\\#@!~^%$]+")


def extract_paths(text: str) -> set[str]:
    """Extract file-path-like strings from text."""
    return set(_PATH_RE.findall(text))


def extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords (4+ chars, not stop words) from text."""
    tokens = _SPLIT_RE.split(text)
    return {
        t.lower()
        for t in tokens
        if len(t) >= MIN_KEYWORD_LEN and t.lower() not in STOP_WORDS
    }


def score_entry(
    entry: Entry, tool_paths: set[str], tool_keywords: set[str]
) -> int:
    """Score a single entry against tool context. Returns score increment."""
    combined = f"{entry.title} {entry.why} {entry.body}"
    entry_paths = extract_paths(combined)
    entry_keywords = extract_keywords(combined)

    score = 0

    # Tier 1: Exact file path match
    if entry_paths & tool_paths:
        score += TIER1_SCORE

    # Tier 2: Directory overlap (same os.path.dirname)
    entry_dirs = {os.path.dirname(p) for p in entry_paths if os.path.dirname(p)}
    tool_dirs = {os.path.dirname(p) for p in tool_paths if os.path.dirname(p)}
    if entry_dirs & tool_dirs:
        score += TIER2_SCORE

    # Tier 3: Keyword overlap (>= 3 shared keywords)
    shared = entry_keywords & tool_keywords
    if len(shared) >= TIER3_MIN_KEYWORDS:
        score += TIER3_SCORE

    return score


def _normalize_path(raw_path: str, cwd: str) -> str:
    """Normalize a path to relative form using cwd."""
    if os.path.isabs(raw_path):
        return os.path.relpath(raw_path, cwd)
    return raw_path


def extract_context_from_tool_input(
    payload: dict,
) -> tuple[set[str], set[str]]:
    """Extract file paths and keywords from a PostToolUse hook payload.

    Returns (paths, keywords).
    """
    paths: set[str] = set()
    keywords: set[str] = set()

    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}

    tool_response = payload.get("tool_response", {})
    if not isinstance(tool_response, dict):
        tool_response = {}

    cwd = payload.get("cwd", "")

    # file_path: Read, Edit, Write
    file_path = tool_input.get("file_path")
    if isinstance(file_path, str) and file_path:
        paths.add(_normalize_path(file_path, cwd) if cwd else file_path)

    # path: Grep, Glob
    path = tool_input.get("path")
    if isinstance(path, str) and path:
        paths.add(_normalize_path(path, cwd) if cwd else path)

    # pattern: Grep, Glob → keywords
    pattern = tool_input.get("pattern")
    if isinstance(pattern, str) and pattern:
        keywords.update(extract_keywords(pattern))

    # old_string, new_string: Edit → keywords
    for field in ("old_string", "new_string"):
        val = tool_input.get(field)
        if isinstance(val, str) and val:
            keywords.update(extract_keywords(val))

    # command: Bash → keywords
    command = tool_input.get("command")
    if isinstance(command, str) and command:
        keywords.update(extract_keywords(command))

    # tool_response.paths: Glob results → paths
    response_paths = tool_response.get("paths")
    if isinstance(response_paths, list):
        for p in response_paths:
            if isinstance(p, str) and p:
                paths.add(_normalize_path(p, cwd) if cwd else p)

    return paths, keywords

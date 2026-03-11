#!/bin/bash
# PostToolUse hook: auto-format Python files after Edit/Write (synchronous).
# Finds black/ruff in the project's venv (bounded by git repo root).
# Order: ruff fix first (may add/remove imports), then black (final formatting).

INPUT=$(cat)

# Use jq for JSON parsing — no python3 PATH dependency
command -v jq >/dev/null 2>&1 || exit 0
FILE_PATH=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // ""' 2>/dev/null)

# Only act on .py files
[[ "$FILE_PATH" != *.py ]] && exit 0
[[ ! -f "$FILE_PATH" ]] && exit 0

# Find tools: prefer project venv, bounded by git repo root
DIR=$(dirname "$FILE_PATH")
VENV=""

# Get git repo root (if in a repo)
REPO_ROOT=$(git -C "$DIR" rev-parse --show-toplevel 2>/dev/null) || REPO_ROOT=""

# Security: files outside git repos are intentionally not formatted (CWE-427)
SEARCH="$DIR"
while [[ -n "$REPO_ROOT" && "$SEARCH" != "/" ]]; do
  if [[ -d "$SEARCH/.venv" ]]; then VENV="$SEARCH/.venv/bin"; break; fi
  # Stop at repo root — never search above it
  [[ "$SEARCH" == "$REPO_ROOT" ]] && break
  SEARCH=$(dirname "$SEARCH")
done

# Security: only use venv tools, never fall back to PATH (CWE-427)
[[ -z "$VENV" ]] && exit 0

BLACK="$VENV/black"
RUFF="$VENV/ruff"

# Ruff fix first (may restructure code), then black for final formatting
command -v "$RUFF" &>/dev/null && "$RUFF" check --fix --quiet "$FILE_PATH" 2>/dev/null
command -v "$BLACK" &>/dev/null && "$BLACK" --quiet "$FILE_PATH" 2>/dev/null

exit 0

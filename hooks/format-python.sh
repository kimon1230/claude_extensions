#!/bin/bash
# PostToolUse hook: auto-format Python files after Edit/Write (synchronous).
# Finds black/ruff in the project's venv or falls back to PATH.
# Order: ruff fix first (may add/remove imports), then black (final formatting).

INPUT=$(cat)
FILE_PATH=$(python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" <<< "$INPUT")

# Only act on .py files
[[ "$FILE_PATH" != *.py ]] && exit 0
[[ ! -f "$FILE_PATH" ]] && exit 0

# Find tools: prefer project venv, fall back to PATH
DIR=$(dirname "$FILE_PATH")
VENV=""
SEARCH="$DIR"
while [[ "$SEARCH" != "/" ]]; do
  if [[ -d "$SEARCH/.venv" ]]; then
    VENV="$SEARCH/.venv/bin"
    break
  fi
  SEARCH=$(dirname "$SEARCH")
done

BLACK="${VENV:+$VENV/}black"
RUFF="${VENV:+$VENV/}ruff"

# Ruff fix first (may restructure code), then black for final formatting
command -v "$RUFF" &>/dev/null && "$RUFF" check --fix --quiet "$FILE_PATH" 2>/dev/null
command -v "$BLACK" &>/dev/null && "$BLACK" --quiet "$FILE_PATH" 2>/dev/null

exit 0

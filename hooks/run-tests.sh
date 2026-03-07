#!/bin/bash
# Stop hook: run pytest when Claude finishes responding.
# Only runs if we're in a Python project with a test suite and files actually changed.
# Exit 1 = non-blocking warning. Stderr visible in verbose mode (Ctrl+O) only.
# Claude does NOT see exit 1 output — no loop risk. This is a user notification.

# Find project root. Prefer CLAUDE_PROJECT_DIR (set by Claude Code), fall back to PWD.
find_project_root() {
  local dir="${CLAUDE_PROJECT_DIR:-$PWD}"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/pyproject.toml" || -f "$dir/setup.py" || -f "$dir/setup.cfg" ]]; then
      echo "$dir"
      return 0
    fi
    dir=$(dirname "$dir")
  done
  return 1
}

ROOT=$(find_project_root) || exit 0

# Find pytest in venv or PATH
PYTEST=""
if [[ -x "$ROOT/.venv/bin/pytest" ]]; then
  PYTEST="$ROOT/.venv/bin/pytest"
elif command -v pytest &>/dev/null; then
  PYTEST="pytest"
else
  exit 0
fi

# Only run if tests directory exists
[[ -d "$ROOT/tests" || -d "$ROOT/test" ]] || exit 0

# Skip if no files were actually modified (pure-text responses, research, etc.)
# Non-git projects: skip entirely (no reliable change detection)
if ! command -v git &>/dev/null || ! git -C "$ROOT" rev-parse --is-inside-work-tree &>/dev/null; then
  exit 0
fi
CHANGED=$(git -C "$ROOT" diff --name-only 2>/dev/null; git -C "$ROOT" diff --cached --name-only 2>/dev/null; git -C "$ROOT" ls-files --others --exclude-standard 2>/dev/null)
[[ -z "$CHANGED" ]] && exit 0

# Run tests from project root (so conftest.py and pyproject.toml config are found).
# pipefail ensures $? reflects pytest's exit code, not tail's.
set -o pipefail
OUTPUT=$(cd "$ROOT" && "$PYTEST" --tb=short -q --no-header -x . 2>&1 | tail -n 50)
EXIT_CODE=$?

if [[ $EXIT_CODE -ne 0 ]]; then
  echo "Tests failed:" >&2
  echo "$OUTPUT" >&2
  exit 1
fi

exit 0

#!/usr/bin/env bash
# Smoke tests for statusline-command.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATUSLINE="$SCRIPT_DIR/statusline-command.sh"
PASS=0
FAIL=0

# --- Assertion helpers ---

assert_contains() {
    local test_name="$1" output="$2" pattern="$3"
    if printf '%s' "$output" | grep -qF "$pattern"; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        printf "FAIL: %s — expected '%s' in output\n" "$test_name" "$pattern" >&2
    fi
}

assert_not_contains() {
    local test_name="$1" output="$2" pattern="$3"
    if ! printf '%s' "$output" | grep -qF "$pattern"; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        printf "FAIL: %s — unexpected '%s' in output\n" "$test_name" "$pattern" >&2
    fi
}

assert_empty() {
    local test_name="$1" output="$2"
    if [ -z "$output" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        printf "FAIL: %s — expected empty output, got: '%s'\n" "$test_name" "$output" >&2
    fi
}

assert_exit_zero() {
    local test_name="$1"
    shift
    if "$@" >/dev/null 2>&1; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        printf "FAIL: %s — non-zero exit\n" "$test_name" >&2
    fi
}

# Guard: skip all tests if jq is not available (matches statusline behavior)
if ! command -v jq >/dev/null 2>&1; then
    printf "SKIP: jq not found, cannot run statusline tests\n"
    exit 0
fi

# --- Test fixtures ---

MINIMAL_JSON='{"model":{"display_name":"Claude Sonnet 4"},"workspace":{"current_dir":"/tmp"}}'

FULL_JSON='{"model":{"display_name":"Claude Sonnet 4"},"workspace":{"current_dir":"/tmp"},"cost":{"total_cost_usd":1.23},"context_window":{"context_window_size":1000000,"used_percentage":55},"worktree":{"name":"feat-branch"}}'

MISSING_OPTIONAL_JSON='{"model":{"display_name":"Claude Sonnet 4"},"workspace":{"current_dir":"/tmp"}}'

ZERO_COST_JSON='{"model":{"display_name":"Claude Sonnet 4"},"workspace":{"current_dir":"/tmp"},"cost":{"total_cost_usd":0}}'

NORMAL_CTX_JSON='{"model":{"display_name":"Claude Sonnet 4"},"workspace":{"current_dir":"/tmp"},"context_window":{"context_window_size":200000,"used_percentage":30}}'

EXTENDED_CTX_JSON='{"model":{"display_name":"Claude Sonnet 4"},"workspace":{"current_dir":"/tmp"},"context_window":{"context_window_size":1000000,"used_percentage":30}}'

WORKTREE_JSON='{"model":{"display_name":"Claude Sonnet 4"},"workspace":{"current_dir":"/tmp"},"worktree":{"name":"my-feature"}}'

NO_WORKTREE_JSON='{"model":{"display_name":"Claude Sonnet 4"},"workspace":{"current_dir":"/tmp"}}'

LONG_WORKTREE_JSON='{"model":{"display_name":"Claude Sonnet 4"},"workspace":{"current_dir":"/tmp"},"worktree":{"name":"this-is-a-very-long-worktree-name-that-exceeds-twenty"}}'

# --- 1. Minimal JSON: no crash, no "null" strings, exit 0 ---

output=$(printf '%s' "$MINIMAL_JSON" | bash "$STATUSLINE" 2>&1)
rc=$?
assert_exit_zero "minimal: exit 0" bash -c "printf '%s' '$MINIMAL_JSON' | bash '$STATUSLINE'"
assert_contains "minimal: model name present" "$output" "Sonnet 4"
assert_not_contains "minimal: no literal null" "$output" "null"

# --- 2. Full JSON: all indicators present ---

output=$(printf '%s' "$FULL_JSON" | bash "$STATUSLINE" 2>&1)
assert_contains "full: cost indicator" "$output" '$'
assert_contains "full: EXT tag" "$output" "[EXT]"
assert_contains "full: worktree tag" "$output" "[wt:"
assert_contains "full: context bar percentage" "$output" "55%"
assert_contains "full: model name" "$output" "Sonnet 4"

# --- 3. Empty string: empty output, exit 0 ---

output=$(printf '' | bash "$STATUSLINE" 2>&1)
assert_empty "empty input: no output" "$output"
assert_exit_zero "empty input: exit 0" bash -c "printf '' | bash '$STATUSLINE'"

# --- 4. Malformed JSON: empty output, exit 0 ---

output=$(printf '%s' '{not json}' | bash "$STATUSLINE" 2>&1)
assert_empty "malformed JSON: no output" "$output"
assert_exit_zero "malformed JSON: exit 0" bash -c "printf '%s' '{not json}' | bash '$STATUSLINE'"

# --- 5. Missing optional fields: graceful degradation ---

output=$(printf '%s' "$MISSING_OPTIONAL_JSON" | bash "$STATUSLINE" 2>&1)
assert_contains "missing optional: model shown" "$output" "Sonnet 4"
assert_not_contains "missing optional: no cost" "$output" '$'
assert_not_contains "missing optional: no worktree" "$output" "[wt:"
assert_not_contains "missing optional: no EXT" "$output" "[EXT]"
assert_not_contains "missing optional: no null" "$output" "null"

# --- 6. Zero cost: should NOT show cost indicator ---

output=$(printf '%s' "$ZERO_COST_JSON" | bash "$STATUSLINE" 2>&1)
assert_not_contains "zero cost: no dollar sign" "$output" '$'

# --- 7. Normal context window (200000): should NOT show [EXT] ---

output=$(printf '%s' "$NORMAL_CTX_JSON" | bash "$STATUSLINE" 2>&1)
assert_not_contains "normal ctx: no EXT" "$output" "[EXT]"
assert_contains "normal ctx: percentage shown" "$output" "30%"

# --- 8. Extended context (1000000): should show [EXT] ---

output=$(printf '%s' "$EXTENDED_CTX_JSON" | bash "$STATUSLINE" 2>&1)
assert_contains "extended ctx: EXT shown" "$output" "[EXT]"

# --- 9. Worktree present: should show [wt: prefix ---

output=$(printf '%s' "$WORKTREE_JSON" | bash "$STATUSLINE" 2>&1)
assert_contains "worktree present: wt tag" "$output" "[wt:my-feature]"

# --- 10. Worktree absent: should NOT show [wt: ---

output=$(printf '%s' "$NO_WORKTREE_JSON" | bash "$STATUSLINE" 2>&1)
assert_not_contains "worktree absent: no wt tag" "$output" "[wt:"

# --- 11. No "null" strings in any output ---
# (Already tested in minimal and missing-optional; test with full JSON too)

output=$(printf '%s' "$FULL_JSON" | bash "$STATUSLINE" 2>&1)
assert_not_contains "full: no literal null" "$output" "null"

# --- 12. Long worktree name: truncated to 20 chars ---

output=$(printf '%s' "$LONG_WORKTREE_JSON" | bash "$STATUSLINE" 2>&1)
assert_contains "long worktree: wt tag present" "$output" "[wt:"
# The truncated name should be the first 20 chars
assert_contains "long worktree: truncated" "$output" "this-is-a-very-long-"
assert_not_contains "long worktree: not full name" "$output" "this-is-a-very-long-worktree-name-that-exceeds-twenty"

# --- Summary ---

printf "\n%d passed, %d failed\n" "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1

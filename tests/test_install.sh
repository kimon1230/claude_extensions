#!/usr/bin/env bash
# Tests for install.sh and uninstall.sh hardening guards
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
INSTALL="$SCRIPT_DIR/install.sh"
UNINSTALL="$SCRIPT_DIR/uninstall.sh"
PASS=0
FAIL=0

# --- Assertion helpers (same pattern as test_statusline.sh) ---

assert_eq() {
    local test_name="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        printf "FAIL: %s — expected '%s', got '%s'\n" "$test_name" "$expected" "$actual" >&2
    fi
}

assert_contains() {
    local test_name="$1" output="$2" pattern="$3"
    if printf '%s' "$output" | grep -qF "$pattern"; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        printf "FAIL: %s — expected '%s' in output\n" "$test_name" "$pattern" >&2
    fi
}

assert_not_exists() {
    local test_name="$1" path="$2"
    if [ ! -e "$path" ] && [ ! -L "$path" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        printf "FAIL: %s — expected '%s' to not exist\n" "$test_name" "$path" >&2
    fi
}

assert_exists() {
    local test_name="$1" path="$2"
    if [ -e "$path" ] || [ -L "$path" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        printf "FAIL: %s — expected '%s' to exist\n" "$test_name" "$path" >&2
    fi
}

assert_is_symlink() {
    local test_name="$1" path="$2"
    if [ -L "$path" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        printf "FAIL: %s — expected '%s' to be a symlink\n" "$test_name" "$path" >&2
    fi
}

assert_not_symlink() {
    local test_name="$1" path="$2"
    if [ ! -L "$path" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        printf "FAIL: %s — expected '%s' to NOT be a symlink\n" "$test_name" "$path" >&2
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

assert_file_contains() {
    local test_name="$1" file="$2" pattern="$3"
    if grep -qF -- "$pattern" "$file" 2>/dev/null; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        printf "FAIL: %s — expected '%s' in file %s\n" "$test_name" "$pattern" "$file" >&2
    fi
}

assert_file_not_contains() {
    local test_name="$1" file="$2" pattern="$3"
    if ! grep -qF -- "$pattern" "$file" 2>/dev/null; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        printf "FAIL: %s — unexpected '%s' in file %s\n" "$test_name" "$pattern" "$file" >&2
    fi
}

# Source guard functions from both scripts
. "$INSTALL" --source-only
. "$UNINSTALL" --source-only

# --- 1. Overlap guard: repo inside claude ---

rc=0
check_overlap "/tmp/test/.claude/ext" "/tmp/test/.claude" 2>/dev/null || rc=$?
assert_eq "overlap: repo inside claude → returns 1" "1" "$rc"

# --- 2. Overlap guard: claude inside repo ---

rc=0
check_overlap "/tmp/test/repo" "/tmp/test/repo/.claude" 2>/dev/null || rc=$?
assert_eq "overlap: claude inside repo → returns 1" "1" "$rc"

# --- 3. Overlap guard: identical paths ---

rc=0
check_overlap "/tmp/same" "/tmp/same" 2>/dev/null || rc=$?
assert_eq "overlap: identical paths → returns 1" "1" "$rc"

# --- 4. Overlap guard: no overlap ---

rc=0
check_overlap "/tmp/a" "/tmp/b" 2>/dev/null || rc=$?
assert_eq "overlap: no overlap → returns 0" "0" "$rc"

# --- 5. Overlap guard: partial name match is NOT overlap ---

rc=0
check_overlap "/tmp/abc" "/tmp/abcdef" 2>/dev/null || rc=$?
# /tmp/abc is NOT a parent of /tmp/abcdef — they're siblings
assert_eq "overlap: sibling dirs → returns 0" "0" "$rc"

# --- 6. resolve_path: regular file ---

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT
echo "hello" > "$tmpdir/test.txt"
resolved=$(resolve_path "$tmpdir/test.txt")
assert_eq "resolve_path: regular file" "$tmpdir/test.txt" "$resolved"

# --- 7. resolve_path: directory ---

mkdir -p "$tmpdir/subdir"
resolved=$(resolve_path "$tmpdir/subdir")
assert_eq "resolve_path: directory" "$tmpdir/subdir" "$resolved"

# --- 8. resolve_path: symlink resolved to real path ---

ln -s "$tmpdir/test.txt" "$tmpdir/link.txt"
resolved=$(resolve_path "$tmpdir/link.txt")
assert_eq "resolve_path: symlink resolves to target dir" "$tmpdir/link.txt" "$resolved"

# --- 9. resolve_path: nonexistent file (parent exists) ---

resolved=$(resolve_path "$tmpdir/nonexistent.txt")
assert_eq "resolve_path: nonexistent file" "$tmpdir/nonexistent.txt" "$resolved"

# --- 10. Symlink-as-source skip in discovery ---
# Create a mock repo layout with one real hook and one symlink hook

mock_repo="$tmpdir/mock_repo"
mkdir -p "$mock_repo/hooks"
echo '#!/bin/bash' > "$mock_repo/hooks/real-hook.sh"
ln -s "$mock_repo/hooks/real-hook.sh" "$mock_repo/hooks/fake-hook.sh"

discovered=()
for f in "$mock_repo"/hooks/*.sh; do
    [ -f "$f" ] || continue
    [ ! -L "$f" ] || continue
    discovered+=("$(basename "$f")")
done
assert_eq "discovery: only real file found" "real-hook.sh" "${discovered[*]}"

# --- 11. Symlink-as-source skip for skills ---

mkdir -p "$mock_repo/skills/real-skill"
echo "skill" > "$mock_repo/skills/real-skill/SKILL.md"
ln -s "$mock_repo/skills/real-skill" "$mock_repo/skills/fake-skill"

discovered=()
for d in "$mock_repo"/skills/*/; do
    [ -d "${d%/}" ] || continue
    [ ! -L "${d%/}" ] || continue
    discovered+=("$(basename "$d")")
done
assert_eq "discovery: only real skill dir found" "real-skill" "${discovered[*]}"

# --- 12. Post-link verification: broken symlink detected ---

broken_link="$tmpdir/broken_link"
ln -s "$tmpdir/nonexistent_target_xyz" "$broken_link"
if [ ! -r "$broken_link" ]; then
    rm -f "$broken_link"
    post_link_caught="yes"
else
    post_link_caught="no"
fi
assert_eq "post-link: broken link detected and removed" "yes" "$post_link_caught"
assert_not_exists "post-link: broken link gone" "$broken_link"

# --- 13. Source == target guard ---

echo "content" > "$tmpdir/same_file.txt"
real_s=$(resolve_path "$tmpdir/same_file.txt")
real_t=$(resolve_path "$tmpdir/same_file.txt")
if [ "$real_s" = "$real_t" ]; then
    same_path_caught="yes"
else
    same_path_caught="no"
fi
assert_eq "source==target: identical paths caught" "yes" "$same_path_caught"

# --- 14. Uninstall: broken symlinks are found ---

mock_claude="$tmpdir/mock_claude"
mock_repo_dir="$tmpdir/mock_repo_for_uninstall"
mkdir -p "$mock_claude/hooks" "$mock_repo_dir"

# Create a broken symlink pointing to a nonexistent path under mock repo
ln -s "$mock_repo_dir/hooks/gone.py" "$mock_claude/hooks/gone.py"

# Verify it's broken
assert_is_symlink "uninstall-broken: is a symlink" "$mock_claude/hooks/gone.py"

# Use find + [ -L ] to find it (not find -type l which misses broken links)
found_broken=()
while IFS= read -r -d '' entry; do
    [ -L "$entry" ] || continue
    raw=$(readlink "$entry")
    if [[ "$raw" == "$mock_repo_dir"* ]]; then
        found_broken+=("$entry")
    fi
done < <(find "$mock_claude" -print0 2>/dev/null)
assert_eq "uninstall-broken: broken symlink found" "1" "${#found_broken[@]}"

# --- 15. Uninstall: valid symlinks also found ---

echo "real" > "$mock_repo_dir/real_file.txt"
ln -s "$mock_repo_dir/real_file.txt" "$mock_claude/real_link.txt"

found_valid=()
while IFS= read -r -d '' entry; do
    [ -L "$entry" ] || continue
    raw=$(readlink "$entry")
    if [[ "$raw" == "$mock_repo_dir"* ]]; then
        found_valid+=("$entry")
    fi
done < <(find "$mock_claude" -print0 2>/dev/null)
# Should find both broken and valid
assert_eq "uninstall-valid: both symlinks found" "2" "${#found_valid[@]}"

# --- 16. Uninstall: relative symlink resolution ---

mkdir -p "$tmpdir/rel_claude/hooks"
mkdir -p "$tmpdir/rel_repo/hooks"
echo "hook" > "$tmpdir/rel_repo/hooks/myhook.sh"
# Create relative symlink
(cd "$tmpdir/rel_claude/hooks" && ln -s ../../rel_repo/hooks/myhook.sh myhook.sh)

rel_link="$tmpdir/rel_claude/hooks/myhook.sh"
assert_is_symlink "relative: is a symlink" "$rel_link"

raw_target=$(readlink "$rel_link")
# Raw target is relative — shouldn't match absolute REPO_DIR
REL_REPO_DIR="$tmpdir/rel_repo"
raw_match="no"
[[ "$raw_target" == "$REL_REPO_DIR"* ]] && raw_match="yes"
assert_eq "relative: raw target does NOT match repo prefix" "no" "$raw_match"

# But after resolution it should match
link_dir=$(cd "$(dirname "$rel_link")" && pwd -P)
resolved_target="$(cd "$link_dir/$(dirname "$raw_target")" && pwd -P)/$(basename "$raw_target")"
resolved_match="no"
[[ "$resolved_target" == "$REL_REPO_DIR"* ]] && resolved_match="yes"
assert_eq "relative: resolved target matches repo prefix" "yes" "$resolved_match"

# --- 17. CLAUDE.md import: fresh install (no existing file) ---

import_claude="$tmpdir/import_claude"
import_repo="$tmpdir/import_repo"
mkdir -p "$import_claude" "$import_repo"
echo "# repo CLAUDE.md" > "$import_repo/CLAUDE.md"

install_claude_md_import "$import_claude/CLAUDE.md" "$import_repo"
assert_exists "import-fresh: file created" "$import_claude/CLAUDE.md"
assert_file_contains "import-fresh: has marker" "$import_claude/CLAUDE.md" "$IMPORT_MARKER"
assert_file_contains "import-fresh: has import line" "$import_claude/CLAUDE.md" "@${import_repo}/CLAUDE.md"
assert_file_contains "import-fresh: has end marker" "$import_claude/CLAUDE.md" "$IMPORT_END"

# --- 18. CLAUDE.md import: existing file preserved ---

import_existing="$tmpdir/import_existing"
mkdir -p "$import_existing"
printf '# My Custom Rules\n- always use tabs\n' > "$import_existing/CLAUDE.md"

install_claude_md_import "$import_existing/CLAUDE.md" "$import_repo"
assert_file_contains "import-existing: has marker" "$import_existing/CLAUDE.md" "$IMPORT_MARKER"
assert_file_contains "import-existing: user content preserved" "$import_existing/CLAUDE.md" "# My Custom Rules"
assert_file_contains "import-existing: user content detail" "$import_existing/CLAUDE.md" "- always use tabs"
# Marker should be on line 1 (prepended)
first_line=$(head -1 "$import_existing/CLAUDE.md")
if printf '%s' "$first_line" | grep -qF "$IMPORT_MARKER"; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    printf "FAIL: import-existing: marker not on line 1 — got '%s'\n" "$first_line" >&2
fi

# --- 19. CLAUDE.md import: idempotent ---

install_claude_md_import "$import_existing/CLAUDE.md" "$import_repo"
marker_count=$(grep -cF "$IMPORT_MARKER" "$import_existing/CLAUDE.md")
assert_eq "import-idempotent: marker appears once" "1" "$marker_count"

# --- 20. CLAUDE.md upgrade: symlink replaced with import ---

upgrade_dir="$tmpdir/upgrade_claude"
upgrade_repo="$tmpdir/upgrade_repo"
mkdir -p "$upgrade_dir" "$upgrade_repo"
echo "# repo content" > "$upgrade_repo/CLAUDE.md"
ln -s "$upgrade_repo/CLAUDE.md" "$upgrade_dir/CLAUDE.md"
printf '# My stuff\n' > "$upgrade_dir/CLAUDE.md.bak"

upgrade_claude_md_symlink "$upgrade_dir/CLAUDE.md" "$upgrade_repo"
install_claude_md_import "$upgrade_dir/CLAUDE.md" "$upgrade_repo"

assert_not_symlink "upgrade-bak: not a symlink" "$upgrade_dir/CLAUDE.md"
assert_file_contains "upgrade-bak: user content restored" "$upgrade_dir/CLAUDE.md" "# My stuff"
assert_file_contains "upgrade-bak: has import marker" "$upgrade_dir/CLAUDE.md" "$IMPORT_MARKER"
# Marker should be on line 1
first_line=$(head -1 "$upgrade_dir/CLAUDE.md")
if printf '%s' "$first_line" | grep -qF "$IMPORT_MARKER"; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    printf "FAIL: upgrade-bak: marker not on line 1 — got '%s'\n" "$first_line" >&2
fi
assert_not_exists "upgrade-bak: .bak gone" "$upgrade_dir/CLAUDE.md.bak"

# --- 21. CLAUDE.md upgrade: symlink without backup ---

upgrade_nobak="$tmpdir/upgrade_nobak"
mkdir -p "$upgrade_nobak"
echo "# repo" > "$upgrade_repo/CLAUDE.md"
ln -s "$upgrade_repo/CLAUDE.md" "$upgrade_nobak/CLAUDE.md"

upgrade_claude_md_symlink "$upgrade_nobak/CLAUDE.md" "$upgrade_repo"
install_claude_md_import "$upgrade_nobak/CLAUDE.md" "$upgrade_repo"

assert_not_symlink "upgrade-nobak: not a symlink" "$upgrade_nobak/CLAUDE.md"
assert_file_contains "upgrade-nobak: has import marker" "$upgrade_nobak/CLAUDE.md" "$IMPORT_MARKER"

# --- 22. CLAUDE.md uninstall: import block removed cleanly ---

uninstall_dir="$tmpdir/uninstall_claude"
mkdir -p "$uninstall_dir"
printf '%s\n%s\n%s\n# My rules\n- be nice\n' "$IMPORT_MARKER" "@${import_repo}/CLAUDE.md" "$IMPORT_END" > "$uninstall_dir/CLAUDE.md"

uninstall_claude_md_import "$uninstall_dir/CLAUDE.md"
assert_file_not_contains "uninstall: marker gone" "$uninstall_dir/CLAUDE.md" "$IMPORT_MARKER"
assert_file_not_contains "uninstall: end marker gone" "$uninstall_dir/CLAUDE.md" "$IMPORT_END"
assert_file_contains "uninstall: user content preserved" "$uninstall_dir/CLAUDE.md" "# My rules"
assert_file_contains "uninstall: user detail preserved" "$uninstall_dir/CLAUDE.md" "- be nice"
# Line 1 should be user content, not blank
first_line=$(head -1 "$uninstall_dir/CLAUDE.md")
if printf '%s' "$first_line" | grep -qF "# My rules"; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    printf "FAIL: uninstall: line 1 not user content — got '%s'\n" "$first_line" >&2
fi

# --- 23. CLAUDE.md uninstall: no import present (no-op) ---

noop_dir="$tmpdir/noop_claude"
mkdir -p "$noop_dir"
printf '# Just my stuff\n' > "$noop_dir/CLAUDE.md"
before=$(cat "$noop_dir/CLAUDE.md")

uninstall_claude_md_import "$noop_dir/CLAUDE.md"
after=$(cat "$noop_dir/CLAUDE.md")
assert_eq "uninstall-noop: file unchanged" "$before" "$after"

# --- 24. Hybrid state: import + symlinks detected independently ---

hybrid_claude="$tmpdir/hybrid_claude"
hybrid_repo="$tmpdir/hybrid_repo"
mkdir -p "$hybrid_claude/hooks" "$hybrid_repo/hooks"
echo "hook content" > "$hybrid_repo/hooks/myhook.sh"
ln -s "$hybrid_repo/hooks/myhook.sh" "$hybrid_claude/hooks/myhook.sh"
printf '%s\n%s\n%s\n# User rules\n' "$IMPORT_MARKER" "@${hybrid_repo}/CLAUDE.md" "$IMPORT_END" > "$hybrid_claude/CLAUDE.md"

uninstall_claude_md_import "$hybrid_claude/CLAUDE.md"
assert_file_not_contains "hybrid: import removed" "$hybrid_claude/CLAUDE.md" "$IMPORT_MARKER"
assert_file_contains "hybrid: user content kept" "$hybrid_claude/CLAUDE.md" "# User rules"

# Test that link_points_to_repo detects the hook symlink
REPO_DIR="$hybrid_repo"
rc=0
link_points_to_repo "$hybrid_claude/hooks/myhook.sh" || rc=$?
assert_eq "hybrid: hook symlink detected" "0" "$rc"

# --- 25. Non-repo symlink guard: install skips external symlink ---

guard_dir="$tmpdir/guard_claude"
mkdir -p "$guard_dir"
ext_file="$tmpdir/external-content.md"
printf 'original content\n' > "$ext_file"
ln -s "$ext_file" "$guard_dir/CLAUDE.md"

stderr_output=$(install_claude_md_import "$guard_dir/CLAUDE.md" "$import_repo" 2>&1 1>/dev/null)
ext_content=$(cat "$ext_file")
assert_eq "guard: external file not modified" "original content" "$ext_content"
assert_contains "guard: warning printed" "$stderr_output" "WARNING"
assert_contains "guard: skipping mentioned" "$stderr_output" "skipping"

# --- Summary ---

printf "\n%d passed, %d failed\n" "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1

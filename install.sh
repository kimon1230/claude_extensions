#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Guard functions (extracted for testability)
# ---------------------------------------------------------------------------

# resolve_path: resolve a path to its canonical absolute form.
# Uses readlink -f where available, falls back to cd+pwd -P.
resolve_path() {
    local p="$1"
    if [ -d "$p" ]; then
        (cd "$p" && pwd -P)
    elif [ -e "$p" ] || [ -L "$p" ]; then
        local dir base
        dir="$(cd "$(dirname "$p")" && pwd -P)"
        base="$(basename "$p")"
        printf '%s/%s' "$dir" "$base"
    else
        # Path doesn't exist yet — resolve parent if possible
        local dir base
        dir="$(cd "$(dirname "$p")" 2>/dev/null && pwd -P)" || { printf '%s' "$p"; return; }
        base="$(basename "$p")"
        printf '%s/%s' "$dir" "$base"
    fi
}

# check_overlap: bail out if REPO_DIR is inside CLAUDE_DIR or vice-versa.
# Prevents recursive symlink disasters.
check_overlap() {
    local repo="$1" claude="$2"
    case "$repo" in
        "$claude"|"$claude"/*)
            printf "ERROR: repo dir (%s) is inside CLAUDE_DIR (%s). Aborting.\n" "$repo" "$claude" >&2
            return 1
            ;;
    esac
    case "$claude" in
        "$repo"|"$repo"/*)
            printf "ERROR: CLAUDE_DIR (%s) is inside repo dir (%s). Aborting.\n" "$claude" "$repo" >&2
            return 1
            ;;
    esac
    return 0
}

# CLAUDE.md @import markers
IMPORT_MARKER="<!-- claude-extensions:import -->"
IMPORT_END="<!-- /claude-extensions:import -->"

upgrade_claude_md_symlink() {
    local claude_md="$1"
    local repo_dir="$2"
    # Is CLAUDE.md a symlink into our repo?
    if [ -L "$claude_md" ]; then
        local link_target
        link_target="$(readlink "$claude_md" 2>/dev/null || true)"
        case "$link_target" in
            "$repo_dir"/*)
                # Old-style install — remove symlink, restore .bak if present
                rm "$claude_md"
                if [ -f "${claude_md}.bak" ]; then
                    mv "${claude_md}.bak" "$claude_md" || {
                        printf "  WARNING: could not restore backup — creating empty file\n" >&2
                        touch "$claude_md"
                    }
                    printf "  CLAUDE.md: migrated from symlink (restored backup)\n"
                else
                    touch "$claude_md"
                    printf "  CLAUDE.md: migrated from symlink (no backup to restore)\n"
                fi
                return 0
                ;;
        esac
    fi
    return 0
}

install_claude_md_import() {
    local claude_md="$1"
    local repo_dir="$2"
    local claude_dir
    claude_dir="$(dirname "$claude_md")"
    local import_line="@${repo_dir}/CLAUDE.md"

    # Create ~/.claude/CLAUDE.md if it doesn't exist
    mkdir -p "$claude_dir"
    [ -f "$claude_md" ] || touch "$claude_md"

    # Guard: if CLAUDE.md is a symlink to something outside our repo, warn and skip
    if [ -L "$claude_md" ]; then
        local link_target
        link_target="$(readlink "$claude_md" 2>/dev/null || true)"
        printf "  WARNING: %s is a symlink to %s — skipping @import to avoid modifying external file\n" "$claude_md" "$link_target" >&2
        return 0
    fi

    # Already has our import? Skip (idempotent)
    if grep -qF "$IMPORT_MARKER" "$claude_md" 2>/dev/null; then
        printf "  CLAUDE.md: @import already present — skipping\n"
        return 0
    fi

    # Prepend the import block (no trailing blank line — keeps uninstall simple)
    local tmp
    tmp=$(mktemp)
    printf '%s\n%s\n%s\n' "$IMPORT_MARKER" "$import_line" "$IMPORT_END" > "$tmp"
    cat "$claude_md" >> "$tmp"
    cat "$tmp" > "$claude_md" && rm "$tmp"
    printf "  CLAUDE.md: added @import for %s/CLAUDE.md\n" "$repo_dir"
}

install_settings() {
    local repo_dir="$1"
    local claude_dir="$2"
    local settings_file="$claude_dir/settings.json"
    local reference_file="$repo_dir/settings.json.reference"

    if [ ! -f "$reference_file" ]; then
        printf "  WARNING: %s not found — skipping settings install\n" "$reference_file" >&2
        return 0
    fi

    if ! command -v jq >/dev/null 2>&1; then
        printf "  WARNING: jq not found — skipping settings.json merge (install jq and re-run)\n" >&2
        return 0
    fi

    # Fresh install: just copy the reference file
    if [ ! -f "$settings_file" ]; then
        mkdir -p "$claude_dir"
        cp "$reference_file" "$settings_file"
        printf "  settings.json: copied from reference (fresh install)\n"
        return 0
    fi

    # Merge: add hooks and statusLine from reference into existing settings
    # Backup before modifying
    cp "$settings_file" "${settings_file}.bak"
    printf "  settings.json: backed up to settings.json.bak\n"

    local ref_hooks ref_statusline existing_hooks merged
    ref_hooks=$(jq '.hooks // {}' "$reference_file")
    ref_statusline=$(jq '.statusLine // null' "$reference_file")

    # Merge hooks: for each hook type (PreToolUse, PostToolUse, etc.),
    # add entries from reference that don't already exist (match on command field)
    merged=$(jq --argjson ref_hooks "$ref_hooks" --argjson ref_sl "$ref_statusline" '
        # Merge hooks using reduce over hook type keys
        .hooks = (
            reduce ($ref_hooks | keys[]) as $hook_type (
                (.hooks // {});
                .[$hook_type] = (
                    (.[$hook_type] // []) as $existing_entries |
                    ($ref_hooks[$hook_type] // []) as $ref_entries |
                    # For each ref entry, add if no existing entry has same matcher+command
                    reduce ($ref_entries[]) as $ref_entry (
                        $existing_entries;
                        ($ref_entry | {matcher: (.matcher // ""), cmds: [.hooks[].command]}) as $ref_id |
                        if any(.[]; {matcher: (.matcher // ""), cmds: [.hooks[].command]} == $ref_id)
                        then .
                        else . + [$ref_entry]
                        end
                    )
                )
            )
        ) |
        # Merge statusLine only if not already set
        if $ref_sl != null and (.statusLine // null) == null then
            .statusLine = $ref_sl
        else .
        end
    ' "$settings_file")

    printf '%s\n' "$merged" > "$settings_file"
    printf "  settings.json: merged hooks and statusLine from reference\n"
}

# --source-only: allow tests to source this file for the guard functions
# without executing the installer.
if [ "${1:-}" = "--source-only" ]; then return 0 2>/dev/null || exit 0; fi

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

REPO_DIR="$(cd "$(dirname "$0")" && pwd -P)"
CLAUDE_DIR="$(cd "$HOME/.claude" 2>/dev/null && pwd -P || printf '%s' "$HOME/.claude")"

# Overlap check — must pass before we discover components
check_overlap "$REPO_DIR" "$CLAUDE_DIR" || exit 1

# ---------------------------------------------------------------------------
# Component discovery
# ---------------------------------------------------------------------------

declare -a COMPONENTS=(
    "Status line|$REPO_DIR/statusline-command.sh|$CLAUDE_DIR/statusline-command.sh"
)

# Discover hooks (skip symlinks)
for f in "$REPO_DIR"/hooks/*.sh "$REPO_DIR"/hooks/*.py; do
    [ -f "$f" ] || continue
    [ ! -L "$f" ] || continue
    name=$(basename "$f")
    COMPONENTS+=("Hook: $name|$f|$CLAUDE_DIR/hooks/$name")
done

# Discover skills (skip symlinks)
for d in "$REPO_DIR"/skills/*/; do
    [ -d "${d%/}" ] || continue
    [ ! -L "${d%/}" ] || continue
    name=$(basename "$d")
    COMPONENTS+=("Skill: $name|$d|$CLAUDE_DIR/skills/$name")
done

# Discover rules (skip symlinks)
for f in "$REPO_DIR"/rules/*.md; do
    [ -f "$f" ] || continue
    [ ! -L "$f" ] || continue
    name=$(basename "$f")
    COMPONENTS+=("Rule: $name|$f|$CLAUDE_DIR/rules/$name")
done

# ---------------------------------------------------------------------------
# Interactive selection
# ---------------------------------------------------------------------------

printf "Claude Code Extensions Installer\n"
printf "=================================\n\n"
printf "This will create symlinks from ~/.claude/ to this repo.\n\n"

CLAUDE_MD="$CLAUDE_DIR/CLAUDE.md"

printf "  Install CLAUDE.md (@import into your existing file)? [Y/n] "
read -r answer </dev/tty
case "$answer" in
    [nN]*) ;;
    *)
        upgrade_claude_md_symlink "$CLAUDE_MD" "$REPO_DIR"
        install_claude_md_import "$CLAUDE_MD" "$REPO_DIR"
        ;;
esac

selected=()
for entry in "${COMPONENTS[@]}"; do
    label="${entry%%|*}"
    printf "  Install %s? [Y/n] " "$label"
    read -r answer </dev/tty
    case "$answer" in
        [nN]*) ;;
        *) selected+=("$entry") ;;
    esac
done

if [ ${#selected[@]} -eq 0 ]; then
    printf "\nNothing selected. Exiting.\n"
    exit 0
fi

printf "\nThe following will be installed:\n"
for entry in "${selected[@]}"; do
    label="${entry%%|*}"
    printf "  - %s\n" "$label"
done

printf "\nExisting files at target paths will be backed up with a .bak suffix.\n"
printf "Proceed? [Y/n] "
read -r confirm </dev/tty
case "$confirm" in
    [nN]*) printf "Aborted.\n"; exit 0 ;;
esac

# ---------------------------------------------------------------------------
# Symlink creation
# ---------------------------------------------------------------------------

printf "\n"
for entry in "${selected[@]}"; do
    IFS='|' read -r label source target <<< "$entry"

    # Source == target guard (e.g., running from inside ~/.claude)
    resolved_source="$(resolve_path "$source")"
    resolved_target="$(resolve_path "$target")"
    if [ "$resolved_source" = "$resolved_target" ]; then
        printf "  SKIP %s: source and target resolve to the same path\n" "$label" >&2
        continue
    fi

    # Ensure target directory exists
    target_dir="$(dirname "$target")"
    if ! mkdir -p "$target_dir"; then
        printf "  ERROR: could not create directory %s — skipping %s\n" "$target_dir" "$label" >&2
        continue
    fi

    # Back up existing file/dir if it's not already a symlink to us
    if [ -e "$target" ] && [ ! -L "$target" ]; then
        mv "$target" "${target}.bak"
        printf "  Backed up %s -> %s.bak\n" "$target" "$target"
    elif [ -L "$target" ]; then
        # Warn if existing symlink doesn't point into our repo
        existing_link="$(readlink "$target" 2>/dev/null || true)"
        case "$existing_link" in
            "$REPO_DIR"/*|"$REPO_DIR") ;;
            *)
                printf "  WARNING: %s points to %s (not in this repo) — replacing\n" "$target" "$existing_link" >&2
                ;;
        esac
        rm "$target"
    fi

    ln -s "$source" "$target"

    # Post-link verification
    if [ ! -r "$target" ]; then
        printf "  WARNING: %s created but unreadable — removing broken link\n" "$target" >&2
        rm -f "$target"
        continue
    fi

    printf "  Linked %s\n" "$label"
done

printf "\n"
if [ -t 0 ]; then
    printf "  Update ~/.claude/settings.json with hook registrations? [Y/n] "
    read -r answer </dev/tty
    case "$answer" in
        [nN]*) ;;
        *) install_settings "$REPO_DIR" "$CLAUDE_DIR" ;;
    esac
else
    install_settings "$REPO_DIR" "$CLAUDE_DIR"
fi

printf "\nDone.\n"

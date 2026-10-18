#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Guard functions (extracted for testability)
# ---------------------------------------------------------------------------

# CLAUDE.md @import markers
IMPORT_MARKER="<!-- claude-extensions:import -->"
IMPORT_END="<!-- /claude-extensions:import -->"

# Resolve a symlink target to an absolute path.
# Handles both absolute and relative readlink output.
resolve_link_target() {
    local link="$1"
    local raw_target
    raw_target=$(readlink "$link") || return 1
    if [[ "$raw_target" == /* ]]; then
        # Absolute target — resolve any .. or intermediate symlinks
        printf '%s' "$(cd "$(dirname "$raw_target")" 2>/dev/null && pwd -P)/$(basename "$raw_target")"
    else
        # Relative target — resolve relative to the symlink's parent dir
        local link_dir
        link_dir=$(cd "$(dirname "$link")" 2>/dev/null && pwd -P) || return 1
        printf '%s' "$(cd "$link_dir/$(dirname "$raw_target")" 2>/dev/null && pwd -P)/$(basename "$raw_target")"
    fi
}

# Check whether a symlink points into REPO_DIR (by raw or resolved target).
link_points_to_repo() {
    local link="$1"
    local raw_target
    raw_target=$(readlink "$link") || return 1

    # Check raw target first (fast path, catches absolute symlinks)
    if [[ "$raw_target" == "$REPO_DIR/"* ]]; then
        return 0
    fi

    # Resolve and check (catches relative symlinks)
    local resolved
    resolved=$(resolve_link_target "$link") || return 1
    [[ "$resolved" == "$REPO_DIR/"* ]]
}

uninstall_claude_md_import() {
    local claude_md="$1"
    [ -f "$claude_md" ] || return 0
    grep -qF "$IMPORT_MARKER" "$claude_md" 2>/dev/null || return 0
    local tmp
    tmp=$(mktemp)
    sed '\|^<!-- claude-extensions:import -->|,\|^<!-- /claude-extensions:import -->|d' "$claude_md" > "$tmp"
    cat "$tmp" > "$claude_md" && rm "$tmp"
    printf "  Removed @import from CLAUDE.md\n"
}

# Deny rules install.sh merges from settings.json.reference (kept in sync by
# tests/test_install.sh, which uninstalls from settings built off the reference).
REPO_DENY_RULES='["Bash(git commit *)","Bash(git push *)"]'

# jq: true when .permissions.deny is an array we can edit. Raw type checks with
# if/elif: in `a or b`, b still runs when a is false, so .permissions.deny would
# error on a string .permissions; and "//" lets false through.
DENY_IS_LIST='def deny_is_list:
    if (.permissions | type) == "object" then (.permissions.deny | type) == "array" else false end;'

# settings_has_repo_entries FILE: succeeds when FILE holds repo-managed hooks, a
# repo statusLine, or the repo deny rules. Fails, without erroring, when the file
# or jq is missing or a check can't parse the file.
settings_has_repo_entries() {
    local settings_file="$1" has_hooks has_statusline has_deny
    { [ -f "$settings_file" ] && command -v jq >/dev/null 2>&1; } || return 1
    has_hooks=$(jq '[.hooks // {} | to_entries[].value[] | select(.hooks[]?.command | tostring | contains("/.claude/hooks/"))] | length' "$settings_file" 2>/dev/null || echo "0")
    has_statusline=$(jq 'if (.statusLine.command // "" | (contains(".claude/statusline-command.sh") or contains(".claude/hooks/statusline.py"))) then 1 else 0 end' "$settings_file" 2>/dev/null || echo "0")
    has_deny=$(jq --argjson repo "$REPO_DENY_RULES" "$DENY_IS_LIST"'
        if deny_is_list then [.permissions.deny[] | select(. as $r | any($repo[]; . == $r))] | length else 0 end
    ' "$settings_file" 2>/dev/null || echo "0")
    [ "$has_hooks" != "0" ] || [ "$has_statusline" != "0" ] || [ "$has_deny" != "0" ]
}

uninstall_settings() {
    local settings_file="$1"

    if [ ! -f "$settings_file" ]; then
        return 0
    fi

    if ! command -v jq >/dev/null 2>&1; then
        printf "  WARNING: jq not found — skipping settings.json cleanup\n" >&2
        return 0
    fi

    # Check if there's anything to remove
    settings_has_repo_entries "$settings_file" || return 0

    # Backup before modifying
    cp "$settings_file" "${settings_file}.bak"
    printf "  settings.json: backed up to settings.json.bak\n"

    local cleaned
    cleaned=$(jq --argjson repo "$REPO_DENY_RULES" "$DENY_IS_LIST"'
        # Remove the repo deny rules (never creates permissions/deny)
        if deny_is_list then .permissions.deny -= $repo else . end |
        # Remove hook entries whose command contains $HOME/.claude/hooks/
        .hooks = ((.hooks // {}) | to_entries | map(
            .value = [.value[] | select(
                (.hooks // []) | all(.command | tostring | contains("/.claude/hooks/") | not)
            )]
        ) | map(select(.value | length > 0)) | from_entries) |
        # Remove hooks key entirely if empty
        if (.hooks | length) == 0 then del(.hooks) else . end |
        # Remove statusLine if it references our statusline script
        if (.statusLine.command // "" | (contains(".claude/statusline-command.sh") or contains(".claude/hooks/statusline.py"))) then del(.statusLine) else . end
    ' "$settings_file")

    printf '%s\n' "$cleaned" > "$settings_file"
    printf "  settings.json: removed claude-extensions settings entries\n"
}

# --source-only: allow tests to source for guard functions without executing main
if [ "${1:-}" = "--source-only" ]; then return 0 2>/dev/null || exit 0; fi

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    # REPO_DIR intentionally non-local — link_points_to_repo reads it
    REPO_DIR="$(cd "$(dirname "$0")" && pwd -P)"
    local CLAUDE_DIR="$HOME/.claude"
    local CLAUDE_MD="$CLAUDE_DIR/CLAUDE.md"

    printf "Claude Code Extensions Uninstaller\n"
    printf "====================================\n\n"
    printf "This will remove symlinks in ~/.claude/ that point into this repo.\n"
    printf "Backed-up files (.bak) will be restored if they exist.\n\n"

    # Handle CLAUDE.md @import removal (before symlink cleanup)
    if [ -t 0 ]; then
        if grep -qF "$IMPORT_MARKER" "$CLAUDE_MD" 2>/dev/null; then
            printf "  Remove @import from CLAUDE.md? [Y/n] "
            read -r answer </dev/tty
            case "$answer" in
                [nN]*) ;;
                *) uninstall_claude_md_import "$CLAUDE_MD" ;;
            esac
        fi
    else
        uninstall_claude_md_import "$CLAUDE_MD"
    fi

    # Find all symlinks under ~/.claude/ that point into our repo.
    # Uses -print0 with [ -L ] test instead of -type l to catch broken symlinks.
    local found=()
    while IFS= read -r -d '' entry; do
        [ -L "$entry" ] || continue
        if link_points_to_repo "$entry"; then
            found+=("$entry")
        fi
    done < <(find "$CLAUDE_DIR" -print0 2>/dev/null)

    if [ ${#found[@]} -eq 0 ]; then
        printf "No symlinks pointing to this repo found. Nothing to do.\n"
        exit 0
    fi

    printf "Found %d installed component(s):\n\n" "${#found[@]}"

    # Interactive per-component selection (requires TTY)
    local selected=()
    if [ -t 0 ]; then
        for link in "${found[@]}"; do
            local short="${link#"$CLAUDE_DIR/"}"
            local backup="${link}.bak"
            if [ -e "$backup" ]; then
                printf "  Uninstall %s? (backup will be restored) [Y/n] " "$short"
            else
                printf "  Uninstall %s? (symlink will be removed) [Y/n] " "$short"
            fi
            read -r answer </dev/tty
            case "$answer" in
                [nN]*) ;;
                *) selected+=("$link") ;;
            esac
        done

        if [ ${#selected[@]} -eq 0 ]; then
            printf "\nNothing selected. Exiting.\n"
            exit 0
        fi

        printf "\nProceed? [Y/n] "
        read -r confirm </dev/tty
        case "$confirm" in
            [nN]*) printf "Aborted.\n"; exit 0 ;;
        esac
    else
        # Non-interactive: select all found symlinks
        selected=("${found[@]}")
    fi

    printf "\n"
    for link in "${selected[@]}"; do
        local short="${link#"$CLAUDE_DIR/"}"
        local backup="${link}.bak"
        rm "$link"
        if [ -e "$backup" ]; then
            mv "$backup" "$link"
            printf "  Restored %s from backup\n" "$short"
        else
            printf "  Removed %s\n" "$short"
        fi
    done

    # Orphaned .bak cleanup — only prompt if interactive
    if [ -t 0 ]; then
        local orphaned_baks=()
        while IFS= read -r -d '' bakfile; do
            local original="${bakfile%.bak}"
            # Only orphaned if the original doesn't exist (wasn't just restored above)
            if [ ! -e "$original" ] && [ ! -L "$original" ]; then
                orphaned_baks+=("$bakfile")
            fi
        done < <(find "$CLAUDE_DIR" -name '*.bak' -print0 2>/dev/null)

        if [ ${#orphaned_baks[@]} -gt 0 ]; then
            printf "\nFound %d orphaned .bak file(s):\n" "${#orphaned_baks[@]}"
            for bak in "${orphaned_baks[@]}"; do
                printf "  %s\n" "${bak#"$CLAUDE_DIR/"}"
            done
            printf "\nRemove orphaned .bak files? [y/N] "
            read -r cleanup </dev/tty
            case "$cleanup" in
                [yY]*)
                    for bak in "${orphaned_baks[@]}"; do
                        rm -rf "$bak"
                        printf "  Removed %s\n" "${bak#"$CLAUDE_DIR/"}"
                    done
                    ;;
            esac
        fi
    fi

    # Clean up settings.json
    local settings_file="$CLAUDE_DIR/settings.json"
    if [ -t 0 ]; then
        if settings_has_repo_entries "$settings_file"; then
            printf "\n  Remove claude-extensions entries (hooks, statusLine, permission rules) from settings.json? [Y/n] "
            read -r answer </dev/tty
            case "$answer" in
                [nN]*) ;;
                *) uninstall_settings "$settings_file" ;;
            esac
        fi
    else
        uninstall_settings "$settings_file"
    fi

    printf "\nDone.\n"
}

main "$@"

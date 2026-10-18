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

# merge_settings_json: compute the merged settings.json content.
# Outputs the merged JSON to stdout. Caller is responsible for precondition checks.
merge_settings_json() {
    local settings_file="$1"
    local reference_file="$2"
    local hooks_dir="${3:-}"
    local drop_sl=false

    local ref_hooks ref_sl ref_deny
    ref_hooks=$(jq '.hooks // {}' "$reference_file")
    ref_sl=$(jq '.statusLine // null' "$reference_file")
    ref_deny=$(jq '.permissions.deny // []' "$reference_file")

    # With a hooks dir, register only hooks whose script is installed there: a
    # registered but missing script exits 2, which Claude Code treats as a
    # blocking error (a declined git-guard.py would deny every Bash call).
    if [ -n "$hooks_dir" ]; then
        local installed f
        installed=$(for f in "$hooks_dir"/*; do
            [ -e "$f" ] && basename "$f"
        done | jq -R . | jq -s .)
        ref_hooks=$(printf '%s' "$ref_hooks" | jq --argjson installed "$installed" '
            map_values(
                map(.hooks |= map(select(
                    ([(.command // "" | tostring) | capture("/\\.claude/hooks/(?<s>[^ \"]+)")][0].s) as $s
                    | $s == null or any($installed[]; . == $s)
                )))
                | map(select(.hooks | length > 0))
            )
            | with_entries(select(.value | length > 0))
        ')
        # Same rule for the status line (a missing script just blanks it)
        [ -e "$hooks_dir/statusline.py" ] || drop_sl=true
    fi

    jq --argjson ref_hooks "$ref_hooks" --argjson ref_sl "$ref_sl" --argjson drop_sl "$drop_sl" \
        --argjson ref_deny "$ref_deny" '
        # permissions / permissions.deny absent, null, or the right type. Raw type
        # checks with if/elif: in `a or b`, b still runs when a is false, so
        # .permissions.deny would error on a string .permissions; and "//" lets
        # false through.
        def deny_mergeable:
            (.permissions | type) as $t
            | if $t == "null" then true
              elif $t == "object" then ((.permissions.deny | type) as $d | $d == "null" or $d == "array")
              else false
              end;

        # Step 1: Strip existing repo-managed hook entries (/.claude/hooks/)
        # so stale entries from older versions are removed before re-adding.
        # User hooks (commands not referencing /.claude/hooks/) are preserved.
        .hooks = ((.hooks // {}) | to_entries | map(
            .value = [.value[] | select(
                (.hooks // []) | all(.command | tostring | contains("/.claude/hooks/") | not)
            )]
        ) | map(select(.value | length > 0)) | from_entries) |

        # Step 2: Add all reference hook entries
        .hooks = (
            reduce ($ref_hooks | keys[]) as $hook_type (
                (.hooks // {});
                .[$hook_type] = ((.[$hook_type] // []) + ($ref_hooks[$hook_type] // []))
            )
        ) |

        # Step 3: Deduplicate within each hook type (defensive, catches edge cases)
        .hooks = (.hooks | to_entries | map(
            .value = (
                reduce .value[] as $entry (
                    [];
                    ($entry | {matcher: (.matcher // ""), cmds: [.hooks[].command]}) as $id |
                    if any(.[]; {matcher: (.matcher // ""), cmds: [.hooks[].command]} == $id)
                    then .
                    else . + [$entry]
                    end
                )
            )
        ) | from_entries) |

        # Step 4: Append the reference deny rules that are missing (git commit/push,
        # layered under git-guard). Existing entries and their order are untouched;
        # a malformed permissions/deny skips only this step.
        if deny_mergeable then
            ($ref_deny - (.permissions.deny // [])) as $missing
            | if ($missing | length) > 0
              then .permissions.deny = ((.permissions.deny // []) + $missing)
              else .
              end
        else .
        end |

        # Step 5: Update statusLine to match reference (replace if repo-managed, set if absent).
        # With statusline.py not installed, remove a repo-managed statusLine instead.
        if $drop_sl then
            if (.statusLine.command // "" | (contains(".claude/statusline-command.sh") or contains(".claude/hooks/statusline.py"))) then
                del(.statusLine)
            else .
            end
        elif $ref_sl != null then
            if (.statusLine // null) == null then
                .statusLine = $ref_sl
            elif (.statusLine.command // "" | (contains(".claude/statusline-command.sh") or contains(".claude/hooks/statusline.py"))) then
                .statusLine = $ref_sl
            else .
            end
        else .
        end
    ' "$settings_file"
}

# install_settings_needed: returns 0 (true) if settings.json needs updating.
install_settings_needed() {
    local repo_dir="$1"
    local claude_dir="$2"
    local settings_file="$claude_dir/settings.json"
    local reference_file="$repo_dir/settings.json.reference"

    # No reference file or no jq — install_settings will warn, so say "needed"
    [ -f "$reference_file" ] || return 0
    command -v jq >/dev/null 2>&1 || return 0

    # No settings file yet — fresh install needed
    [ -f "$settings_file" ] || return 0

    # Compare current vs merged
    local merged existing
    merged=$(merge_settings_json "$settings_file" "$reference_file" "$claude_dir/hooks")
    existing=$(jq '.' "$settings_file")
    [ "$existing" != "$merged" ]
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

    # Fresh install: start from the reference file, then fall through so the
    # merge drops registrations for hooks that aren't installed.
    local fresh=0
    if [ ! -f "$settings_file" ]; then
        mkdir -p "$claude_dir"
        cp "$reference_file" "$settings_file"
        printf "  settings.json: copied from reference (fresh install)\n"
        fresh=1
    fi

    # Merge hooks, statusLine and permission deny rules from reference into existing settings
    local merged
    merged=$(merge_settings_json "$settings_file" "$reference_file" "$claude_dir/hooks")

    # Compare before writing — skip if nothing changed
    local existing
    existing=$(jq '.' "$settings_file")
    if [ "$existing" = "$merged" ]; then
        [ "$fresh" -eq 1 ] || printf "  settings.json: already up to date — skipping\n"
        return 0
    fi

    if [ "$fresh" -eq 0 ]; then
        cp "$settings_file" "${settings_file}.bak"
        printf "  settings.json: backed up to settings.json.bak\n"
    fi
    printf '%s\n' "$merged" > "$settings_file"
    if [ "$fresh" -eq 1 ]; then
        printf "  settings.json: dropped registrations for hooks that aren't installed\n"
    else
        printf "  settings.json: merged hooks, statusLine and permission rules from reference\n"
    fi
}

# discover_skills REPO_DIR: print each installable skill dir, one per line.
# Skips symlinks and dirs without a SKILL.md (e.g. Claude Code's skills/synced/).
discover_skills() {
    local d
    for d in "$1"/skills/*/; do
        [ -d "${d%/}" ] || continue
        [ ! -L "${d%/}" ] || continue
        [ -f "${d}SKILL.md" ] || continue
        printf '%s\n' "$d"
    done
}

# companion_entry MOD_NAME: the entry script an importable *_mod.py belongs to
# (git_guard_mod.py -> git-guard.py, statusline_mod.py -> statusline.py).
companion_entry() {
    local stem="${1%_mod.py}"
    printf '%s.py\n' "${stem//_/-}"
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

# The status line ships as hooks/statusline.py and is discovered by the hooks
# glob below (no special-case entry needed).
declare -a COMPONENTS=()

# Discover hooks (skip symlinks, and __init__.py, which only makes hooks/ an
# importable package for the test suite)
for f in "$REPO_DIR"/hooks/*.sh "$REPO_DIR"/hooks/*.py; do
    [ -f "$f" ] || continue
    [ ! -L "$f" ] || continue
    name=$(basename "$f")
    [ "$name" != "__init__.py" ] || continue
    COMPONENTS+=("Hook: $name|$f|$CLAUDE_DIR/hooks/$name")
done

# Discover skills
while IFS= read -r d; do
    name=$(basename "$d")
    COMPONENTS+=("Skill: $name|$d|$CLAUDE_DIR/skills/$name")
done < <(discover_skills "$REPO_DIR")

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

# Check if CLAUDE.md @import is already present
if grep -qF "$IMPORT_MARKER" "$CLAUDE_MD" 2>/dev/null; then
    printf "  CLAUDE.md: @import already present — skipping\n"
else
    printf "  Install CLAUDE.md (@import into your existing file)? [Y/n] "
    read -r answer </dev/tty
    case "$answer" in
        [nN]*) ;;
        *)
            upgrade_claude_md_symlink "$CLAUDE_MD" "$REPO_DIR"
            install_claude_md_import "$CLAUDE_MD" "$REPO_DIR"
            ;;
    esac
fi

selected=()
deferred_mods=()
already_installed=0
for entry in "${COMPONENTS[@]}"; do
    IFS='|' read -r label source target <<< "$entry"

    # Check if already installed (symlink exists and points to correct source)
    if [ -L "$target" ]; then
        existing_link="$(readlink "$target" 2>/dev/null || true)"
        resolved_source="$(resolve_path "$source")"
        resolved_existing="$(resolve_path "$target")"
        if [ "$existing_link" = "$source" ] || [ "$resolved_existing" = "$resolved_source" ]; then
            printf "  %s: already installed — skipping\n" "$label"
            already_installed=$((already_installed + 1))
            continue
        fi
    fi

    # A *_mod.py is useless without its entry script (and vice versa), so it is
    # never prompted for; it follows its entry script below.
    case "$label" in
        "Hook: "*_mod.py) deferred_mods+=("$entry"); continue ;;
    esac

    printf "  Install %s? [Y/n] " "$label"
    read -r answer </dev/tty
    case "$answer" in
        [nN]*) ;;
        *) selected+=("$entry") ;;
    esac
done

# ${arr[@]+"${arr[@]}"}: bash < 4.4 (macOS /bin/bash 3.2) treats an empty
# "${arr[@]}" as unbound under set -u, and these arrays are empty on a re-run.
for entry in ${deferred_mods[@]+"${deferred_mods[@]}"}; do
    IFS='|' read -r label source target <<< "$entry"
    entry_target="$CLAUDE_DIR/hooks/$(companion_entry "$(basename "$source")")"
    if [ -e "$entry_target" ] || printf '%s\n' ${selected[@]+"${selected[@]}"} | grep -qF "|$entry_target"; then
        selected+=("$entry")
    fi
done

if [ ${#selected[@]} -eq 0 ]; then
    if [ "$already_installed" -eq "${#COMPONENTS[@]}" ]; then
        printf "\nAll components already installed.\n"
    else
        printf "\nNothing new selected.\n"
    fi
else
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
fi
# No early exit when nothing is new: stale-link cleanup and the settings.json
# merge below must still run, or a release that only changes hook
# registrations never reaches an existing install.

# ---------------------------------------------------------------------------
# Symlink creation
# ---------------------------------------------------------------------------

printf "\n"
for entry in ${selected[@]+"${selected[@]}"}; do
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

# ---------------------------------------------------------------------------
# Stale symlink cleanup (upgrade support)
# ---------------------------------------------------------------------------
# After installing, check for broken symlinks under ~/.claude/ that point into
# the repo. These are leftovers from components that were removed or renamed.

stale_links=()
while IFS= read -r -d '' entry; do
    [ -L "$entry" ] || continue
    # Only broken symlinks (target doesn't exist)
    [ -e "$entry" ] && continue
    # Check if it points into our repo
    raw_target=$(readlink "$entry" 2>/dev/null || true)
    case "$raw_target" in
        "$REPO_DIR"/*) stale_links+=("$entry") ;;
    esac
done < <(find "$CLAUDE_DIR" -print0 2>/dev/null)

if [ ${#stale_links[@]} -gt 0 ] && [ -t 0 ]; then
    printf "\nFound %d stale symlink(s) from a previous install:\n" "${#stale_links[@]}"
    for link in "${stale_links[@]}"; do
        printf "  %s -> %s\n" "${link#"$CLAUDE_DIR/"}" "$(readlink "$link" 2>/dev/null)"
    done
    printf "\n  Remove stale symlinks? [Y/n] "
    read -r answer </dev/tty
    case "$answer" in
        [nN]*) ;;
        *)
            for link in "${stale_links[@]}"; do
                local_short="${link#"$CLAUDE_DIR/"}"
                local_backup="${link}.bak"
                rm "$link"
                if [ -e "$local_backup" ]; then
                    mv "$local_backup" "$link"
                    printf "  Restored %s from backup\n" "$local_short"
                else
                    printf "  Removed %s\n" "$local_short"
                fi
            done
            ;;
    esac
elif [ ${#stale_links[@]} -gt 0 ]; then
    # Non-interactive: remove stale links automatically
    for link in "${stale_links[@]}"; do
        rm "$link"
        printf "  Removed stale symlink: %s\n" "${link#"$CLAUDE_DIR/"}"
    done
fi

printf "\n"
# install_settings detects no-ops internally and prints "already up to date — skipping".
# Only prompt the user when there's actually something to merge.
if [ -t 0 ] && install_settings_needed "$REPO_DIR" "$CLAUDE_DIR"; then
    printf "  Update ~/.claude/settings.json (hooks, statusLine, permission rules)? [Y/n] "
    read -r answer </dev/tty
    case "$answer" in
        [nN]*) ;;
        *) install_settings "$REPO_DIR" "$CLAUDE_DIR" ;;
    esac
elif [ -t 0 ]; then
    printf "  settings.json: already up to date — skipping\n"
else
    install_settings "$REPO_DIR" "$CLAUDE_DIR"
fi

printf "\nDone.\n"

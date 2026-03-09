#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"

# Components available for installation: label, source, target
declare -a COMPONENTS=(
    "CLAUDE.md (global instructions)|$REPO_DIR/CLAUDE.md|$CLAUDE_DIR/CLAUDE.md"
    "Status line|$REPO_DIR/statusline-command.sh|$CLAUDE_DIR/statusline-command.sh"
)

# Discover hooks
for f in "$REPO_DIR"/hooks/*.sh "$REPO_DIR"/hooks/*.py; do
    [ -f "$f" ] || continue
    name=$(basename "$f")
    COMPONENTS+=("Hook: $name|$f|$CLAUDE_DIR/hooks/$name")
done

# Discover skills
for d in "$REPO_DIR"/skills/*/; do
    [ -d "$d" ] || continue
    name=$(basename "$d")
    COMPONENTS+=("Skill: $name|$d|$CLAUDE_DIR/skills/$name")
done

# Discover rules
for f in "$REPO_DIR"/rules/*.md; do
    [ -f "$f" ] || continue
    name=$(basename "$f")
    COMPONENTS+=("Rule: $name|$f|$CLAUDE_DIR/rules/$name")
done

printf "Claude Code Extensions Installer\n"
printf "=================================\n\n"
printf "This will create symlinks from ~/.claude/ to this repo.\n\n"

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

printf "\n"
for entry in "${selected[@]}"; do
    IFS='|' read -r label source target <<< "$entry"

    # Ensure target directory exists
    mkdir -p "$(dirname "$target")"

    # Back up existing file/dir if it's not already a symlink to us
    if [ -e "$target" ] && [ ! -L "$target" ]; then
        mv "$target" "${target}.bak"
        printf "  Backed up %s -> %s.bak\n" "$target" "$target"
    elif [ -L "$target" ]; then
        rm "$target"
    fi

    ln -s "$source" "$target"
    printf "  Linked %s\n" "$label"
done

printf "\nDone. Review settings.json.reference for hook/statusline wiring:\n"
printf "  %s/settings.json.reference\n" "$REPO_DIR"

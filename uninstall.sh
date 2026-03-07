#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"

printf "Claude Code Extensions Uninstaller\n"
printf "====================================\n\n"
printf "This will remove symlinks in ~/.claude/ that point into this repo.\n"
printf "Backed-up files (.bak) will be restored if they exist.\n\n"

# Find all symlinks under ~/.claude/ that point into our repo
found=()
while IFS= read -r -d '' link; do
    target=$(readlink "$link")
    if [[ "$target" == "$REPO_DIR"* ]]; then
        found+=("$link")
    fi
done < <(find "$CLAUDE_DIR" -type l -print0 2>/dev/null)

if [ ${#found[@]} -eq 0 ]; then
    printf "No symlinks pointing to this repo found. Nothing to do.\n"
    exit 0
fi

printf "Found %d installed component(s):\n\n" "${#found[@]}"

selected=()
for link in "${found[@]}"; do
    short="${link#"$CLAUDE_DIR/"}"
    backup="${link}.bak"
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

printf "\n"
for link in "${selected[@]}"; do
    short="${link#"$CLAUDE_DIR/"}"
    backup="${link}.bak"
    rm "$link"
    if [ -e "$backup" ]; then
        mv "$backup" "$link"
        printf "  Restored %s from backup\n" "$short"
    else
        printf "  Removed %s\n" "$short"
    fi
done

printf "\nDone. You may also need to remove hook/statusline entries from ~/.claude/settings.json.\n"

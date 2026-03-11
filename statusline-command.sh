#!/usr/bin/env bash
# Claude Code status line — mirrors bash PS1: user@host:cwd + model + context
input=$(cat)

# Guard: require jq
command -v jq >/dev/null 2>&1 || exit 0

# Guard: validate JSON (jq empty accepts empty input, so check explicitly)
[ -n "$input" ] || exit 0
echo "$input" | jq empty 2>/dev/null || exit 0

cwd=$(echo "$input" | jq -r '.workspace.current_dir // .cwd // ""')
model=$(echo "$input" | jq -r '.model.display_name // ""')

# Claude Code's used_percentage underreports by ~10 absolute points because
# current_usage reflects the last API call, not the live context which includes
# new tool results, user messages, and formatting overhead since that call.
# We use the pre-calculated field directly and compensate in the thresholds.
used_int=$(echo "$input" | jq -r '.context_window.used_percentage // empty')
ctx_size=$(echo "$input" | jq -r '.context_window.context_window_size // empty')
cost=$(echo "$input" | jq -r '.cost.total_cost_usd // empty')
worktree_name=$(echo "$input" | jq -r '.worktree.name // empty')

# ANSI color codes (same palette as PS1: bold-green for user@host, bold-blue for path)
bold_green='\033[01;32m'
bold_blue='\033[01;34m'
bold_yellow='\033[01;33m'
reset='\033[00m'

user_host="$(whoami)@$(hostname -s)"
short_cwd="${cwd/#$HOME/\~}"

# Build context progress bar when available (10 cells wide, shows % used)
ctx_part=""
if [ -n "$used_int" ]; then
    remaining_int=$(( 100 - used_int ))

    # Thresholds shifted +10 to compensate for ~10% underreporting.
    # "remaining 25%" reported ≈ actual 15% remaining → red
    # "remaining 40%" reported ≈ actual 30% remaining → yellow
    if [ "$remaining_int" -le 25 ]; then
        ctx_color='\033[01;31m'  # bold-red: critical
    elif [ "$remaining_int" -le 40 ]; then
        ctx_color='\033[01;33m'  # bold-yellow: warning
    else
        ctx_color='\033[01;32m'  # bold-green: healthy
    fi

    # 10-cell bar: filled cells = floor(used_int / 10)
    filled=$(( used_int / 10 ))
    empty=$(( 10 - filled ))
    bar=""
    for (( i=0; i<filled; i++ )); do bar="${bar}█"; done
    for (( i=0; i<empty;  i++ )); do bar="${bar}░"; done

    ctx_part=" ${ctx_color}[${bar} ${used_int}%]${reset}"
fi

# Model short label (strip "Claude " prefix for brevity)
model_label="${model#Claude }"
model_part=""
if [ -n "$model_label" ]; then
    # Extended context indicator for windows > 200k tokens
    ext_tag=""
    if [ -n "$ctx_size" ] && [ "$ctx_size" -gt 200000 ] 2>/dev/null; then
        ext_tag="[EXT]"
    fi
    model_part=" ${bold_yellow}(${model_label}${ext_tag})${reset}"
fi

# Cost display (dim white, after context bar)
dim_white='\033[2;37m'
cost_part=""
if [ -n "$cost" ]; then
    cost_check=$(printf "%.2f" "$cost" 2>/dev/null) || cost_check="0.00"
    if [ "$cost_check" != "0.00" ]; then
        cost_part=" ${dim_white}~\$${cost_check}${reset}"
    fi
fi

# Worktree tag (before user@host)
worktree_part=""
if [ -n "$worktree_name" ]; then
    worktree_name="${worktree_name:0:20}"
    worktree_part="$(printf '[wt:%s] ' "$worktree_name")"
fi

printf "%s${bold_green}%s${reset}:${bold_blue}%s${reset}%b%b%b" \
    "$worktree_part" "$user_host" "$short_cwd" "$model_part" "$ctx_part" "$cost_part"

# Claude Code Extensions

Custom hooks, skills, rules, and configuration for [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

Files in this repo are symlinked or copied into `~/.claude/` to extend Claude Code's behavior.

## Structure

```
├── CLAUDE.md               # Global instructions (symlinked to ~/.claude/CLAUDE.md)
├── install.sh              # Interactive installer — pick components, symlink into ~/.claude/
├── uninstall.sh            # Interactive uninstaller — restore backups or remove symlinks
├── hooks/                  # Event-driven shell hooks
│   ├── format-python.sh    # PostToolUse: auto-format .py files with ruff + black
│   └── run-tests.sh        # Stop: run pytest when Claude finishes responding
├── skills/                 # Custom slash-command skills (/skill-name)
│   ├── save/               # /save — checkpoint session progress to status files
│   ├── critical-review/    # /critical-review — parallel subagent plan review
│   ├── implement-batch/    # /implement-batch — parallel subagent batch implementation
│   └── security-audit/     # /security-audit — parallel subagent security review
├── rules/                  # Language-specific coding conventions
│   ├── python.md           # venv usage, atomic edits around hooks, pathlib, type hints
│   ├── javascript.md       # package manager detection, ES modules, TypeScript prefs
│   └── shell.md            # $HOME over ~, guard tool availability, pipefail
├── statusline-command.sh   # Custom status line: user@host:cwd + model + context bar
└── settings.json.reference # Reference settings.json for ~/.claude/settings.json
```

## Hooks

### `format-python.sh` (PostToolUse)

Runs after every `Edit` or `Write` on `.py` files. Finds `ruff` and `black` in the project's `.venv` (walking up from the edited file) or falls back to `$PATH`. Runs `ruff check --fix` first (import sorting, auto-fixes), then `black` for final formatting.

### `run-tests.sh` (Stop)

Runs `pytest` after Claude finishes responding, but only when:
- The project has a `pyproject.toml`/`setup.py`/`setup.cfg`
- A `tests/` or `test/` directory exists
- Git detects changed files (skips pure-text responses)

Outputs last 50 lines of test output to stderr on failure. Non-blocking (exit 1 = warning only).

## Skills

| Skill | Trigger | Purpose |
|---|---|---|
| `/save` | Manual | Writes `session-progress.md` and `project-status.md` to `~/.claude/status/<project>/` |
| `/critical-review` | Manual | Spawns 4 parallel subagents to review a plan for correctness, edge cases, feasibility, and test coverage. Iterates until no critical/major findings. |
| `/implement-batch` | Manual | Implements one batch of a plan using parallel subagents per module, then validates with full test suite. |
| `/security-audit` | Manual | Spawns 5-6 parallel subagents covering OWASP categories, secrets scanning, and web-specific checks. Includes follow-up verification rounds. |

## Rules

Language-specific conventions loaded as context for all projects. Key highlights:

- **Python**: Always use `.venv/bin/python`. Edits must be atomic (imports + usage in one edit) because the format hook runs between edits.
- **JavaScript/TypeScript**: Detect package manager from lock files. ES modules, strict TypeScript, `const` by default.
- **Shell**: `$HOME` not `~`, guard with `command -v`, `set -o pipefail`.

## Status Line

`statusline-command.sh` renders a PS1-style prompt in the Claude Code UI:

```
user@host:~/project (Sonnet 4.6) [████████░░ 80%]
```

- Green/yellow/red context bar based on remaining context window
- Model name (with "Claude " prefix stripped for brevity)
- Thresholds shifted +10% to compensate for underreported usage

## Settings Reference

`settings.json.reference` shows the full `~/.claude/settings.json` structure including:
- Hook wiring (PostToolUse for formatting, Stop for tests)
- Status line command
- Enabled plugins (`frontend-design`)
- Cleanup period and attribution config

## Installation

This repo is the canonical source for all Claude Code configuration. The install script symlinks selected components into `~/.claude/`, backing up any existing files first.

```bash
./install.sh
```

You'll be prompted for each component (CLAUDE.md, hooks, skills, rules, status line) — pick what you want. Existing files are backed up with a `.bak` suffix before being replaced.

After installing, review `settings.json.reference` and merge the relevant sections (hook wiring, status line, plugins) into your `~/.claude/settings.json`.

To uninstall, run `./uninstall.sh` — it finds symlinks pointing into this repo, lets you pick which to remove, and restores `.bak` files where they exist.

# Claude Code Extensions

Custom hooks, skills, rules, and configuration for [Claude Code](https://code.claude.com/docs/en/overview).

Files in this repo are symlinked or copied into `~/.claude/` to extend Claude Code's behavior.

## Structure

```
├── CLAUDE.md                   # Global instructions (@imported into ~/.claude/CLAUDE.md)
├── install.sh                  # Interactive installer — pick components, symlink into ~/.claude/
├── uninstall.sh                # Interactive uninstaller — restore backups or remove symlinks
├── hooks/                      # Event-driven hooks (shell + Python)
│   ├── format-python.sh        # PostToolUse: auto-format .py files with ruff + black
│   ├── run-tests.sh            # Stop: run pytest when Claude finishes responding
│   ├── ref-scorer.py           # PostToolUse: score status entries against tool context
│   ├── ref_scorer_mod.py       # Importable module for ref-scorer.py
│   ├── session-init.py         # SessionStart: increment session count, check compression triggers
│   ├── session_init_mod.py     # Importable module for session-init.py
│   ├── auto-capture.py         # Stop: generate entries from git diff at session end
│   ├── auto_capture_mod.py     # Importable module for auto-capture.py
│   ├── sensitive-file-guard.py # PreToolUse: block reads of .env, SSH keys, credentials
│   ├── sensitive_file_guard_mod.py # Importable module for sensitive-file-guard.py
│   └── lib/                    # Shared Python libraries (stdlib only)
│       ├── entries.py           # Entry parsing/serialization (typed entries, section-aware)
│       ├── fileutil.py          # Atomic writes, safe JSON read/write with .bak fallback
│       ├── ref_tracker.py       # 3-tier reference scoring logic
│       ├── paths.py             # Project name and status path resolution
│       ├── scribe.py            # Git diff classification (file type detection, entry generation)
│       └── compressor.py        # 4-tier context compression algorithm
├── skills/                     # Custom slash-command skills (/skill-name)
│   ├── save/                   # /save — checkpoint session progress to status files
│   ├── compress/               # /compress — force context compression on demand
│   ├── critical-review/        # /critical-review — parallel subagent plan review
│   ├── implement-batch/        # /implement-batch — parallel subagent batch implementation
│   ├── security-audit/         # /security-audit — parallel subagent security review
│   └── code-review/            # /code-review — parallel subagent code quality review
├── rules/                      # Language-specific coding conventions
│   ├── python.md               # venv usage, atomic edits around hooks, pathlib, type hints
│   ├── javascript.md           # package manager detection, ES modules, TypeScript prefs
│   └── shell.md                # $HOME over ~, guard tool availability, pipefail
├── tests/                      # pytest test suite (402 tests)
├── statusline-command.sh       # Custom status line: user@host:cwd + model + context bar
└── settings.json.reference     # Reference settings.json for ~/.claude/settings.json
```

## Hooks

### `format-python.sh` (PostToolUse)

Runs after every `Edit` or `Write` on `.py` files. Finds `ruff` and `black` in the project's `.venv` (walking up from the edited file). Skips formatting if no venv is found. Runs `ruff check --fix` first (import sorting, auto-fixes), then `black` for final formatting.

### `ref-scorer.py` (PostToolUse)

Runs after `Read`, `Edit`, `Write`, `Grep`, `Glob` tool uses. Scores status entries in `session-progress.md` against the tool context using 3-tier scoring:

| Tier | Signal | Score |
|------|--------|-------|
| 1 | Exact file path match | +2 |
| 2 | Directory overlap | +1 |
| 3 | Keyword overlap (≥3 shared, 4+ chars) | +1 |

Scores accumulate in `~/.claude/status/<project>/ref-cache.json`. Entries with high scores are "active" (relevant); entries with score 0 are "stale". Never crashes — all exceptions silently caught.

### `session-init.py` (SessionStart)

Runs on session startup/resume:
1. Increments `session_count` in `ref-cache.json`
2. Logs context summary to stderr: "Context: N entries, M active, K stale"
3. Checks compression triggers — if any fire, auto-runs the compressor

### `auto-capture.py` (Stop)

Runs after Claude finishes responding. Automatically generates observation entries from uncommitted git changes:
1. Runs `git diff --name-status` to classify changed files (test, config, source, renamed, deleted)
2. Deduplicates against existing entries
3. Appends new observations to a `## Auto-captured` section in `session-progress.md`
4. `/save` later reviews and promotes these entries into the main Completed section

### `run-tests.sh` (Stop)

Runs `pytest` after Claude finishes responding, but only when:
- The project has a `pyproject.toml`/`setup.py`/`setup.cfg`
- A `tests/` or `test/` directory exists
- Git detects changed files (skips pure-text responses)

Outputs last 50 lines of test output to stderr on failure. Non-blocking (exit 1 = warning only).

### `sensitive-file-guard.py` (PreToolUse)

Blocks reads of files matching sensitive patterns before the tool executes. Intercepts both the `Read` tool (checks `file_path`) and `Bash` tool (tokenizes command with `shlex.split()`, checks each token).

**Patterns blocked** (matched against basename, case-insensitive):
- `.env`, `.env.local`, `.env.production`, `.env.staging`, `.env.test`, `.env.development` (but `.env.example`, `.env.sample`, `.envrc` are allowed)
- SSH/TLS keys: `id_rsa*`, `id_ed25519*`, `*.pem`, `*.p12`, `*.pfx`
- `*.key` only when basename contains `private`, `server`, `tls`, or `ssl` (avoids false positives on `translation.key`)
- `credentials` / `secrets` as exact stem (blocks `credentials.json` but not `credentials_validator.py`)
- `.npmrc`, `.pypirc`
- AWS paths: `~/.aws/credentials`, `~/.aws/config`

Returns a JSON block decision with a message directing the user to read the file outside the session if needed. Never crashes — all exceptions caught and logged to stderr.

## Skills

| Skill | Trigger | Purpose |
|---|---|---|
| `/save` | Manual | Writes `session-progress.md` and `project-status.md` to `~/.claude/status/<project>/`. Uses typed entries (decision/observation) with unique IDs. Reviews and promotes auto-captured entries. |
| `/compress` | Manual | Forces context compression on demand, bypassing automatic trigger thresholds. Moves stale entries through tiers: Active → Compressed → Archived → Dropped. |
| `/critical-review` | Manual | Spawns 4 parallel subagents to review a plan for correctness, edge cases, feasibility, and test coverage. Iterates until no critical/major findings. Logs all accept/reject/defer decisions to `decision-log.md`. |
| `/implement-batch` | Manual | Implements one batch of a plan using parallel subagents per module, then validates with full test suite. Includes complexity gate (flags tasks meeting 2-of-3 thresholds), implementer status protocol (DONE/DONE_WITH_CONCERNS/NEEDS_CONTEXT/BLOCKED), contradiction detection, and cascading-fix escalation (3-strike rule). |
| `/security-audit` | Manual | Spawns 6-7 parallel subagents covering OWASP categories, secrets scanning, CI/CD pipeline security, and web-specific checks. Supports IaC detection, PHP detection, and optional compliance frameworks (PCI-DSS, HIPAA, SOC2, GDPR). Includes CTF-sourced detection patterns, rationalizations-to-reject, red flags, BEFORE/AFTER remediation verification, and follow-up rounds. |
| `/code-review` | Manual | Spawns 5 parallel subagents reviewing architecture, code quality, correctness, performance, and maintainability. Language-aware with idiomatic checks. Includes blast radius risk labeling (HIGH/MED/LOW), mock quality detection, rationalizations-to-reject, red flags, BEFORE/AFTER remediation verification, and follow-up rounds. |

## Rules

Language-specific conventions loaded only when working with matching files (via `paths` frontmatter). Key highlights:

- **Python**: Always use `.venv/bin/python`. Edits must be atomic (imports + usage in one edit) because the format hook runs between edits.
- **JavaScript/TypeScript**: Detect package manager from lock files. ES modules, strict TypeScript, `const` by default.
- **Shell**: `$HOME` not `~`, guard with `command -v`, `set -o pipefail`.

## Status Line

`statusline-command.sh` renders a PS1-style prompt in the Claude Code UI:

```
user@host:~/project (Sonnet 4.6) [████████░░ 80%] ~$1.23
```

- Green/yellow/red context bar based on remaining context window
- Model name (with "Claude " prefix stripped for brevity)
- Thresholds shifted +10% to compensate for underreported usage
- Cost estimate (`~$X.XX`) — the `~` prefix indicates this is an approximate API-equivalent cost, not an actual charge. Claude Code reports `total_cost_usd` even on Pro/Max subscriptions as a usage-equivalent metric. Suppressed when $0.00.

## Context Persistence

The hooks and skills above form a context persistence system that helps Claude maintain awareness across sessions. The system works automatically once hooks are activated:

1. **Reference scoring** (`ref-scorer.py`): Every tool use scores status entries by file path and keyword overlap, tracking which entries are actively relevant.
2. **Auto-capture** (`auto-capture.py`): At session end, uncommitted git changes are classified and appended as observation entries.
3. **Manual save** (`/save`): Claude writes typed entries (decisions with sacred `Why:` text, observations) and promotes auto-captured entries.
4. **Compression** (`session-init.py` + `/compress`): Stale entries are automatically compressed when triggers fire (>30 entries, ≥5 sessions idle, or ≥60% stale ratio). Compression moves entries through tiers:

| Tier | Format | Location |
|------|--------|----------|
| Active | Full entry with body/Why | `session-progress.md` |
| Compressed | One-liner, Why preserved for decisions | `project-status.md` → `## Compressed Context` |
| Archived | Title only | `archive.md` |
| Dropped | Gone | — |

Decision `Why:` text is **never** compressed, summarized, or dropped — it transfers verbatim through all tiers.

### Status files

```
~/.claude/status/<project>/
├── session-progress.md    # Current session entries (active tier)
├── project-status.md      # Cumulative project history + compressed entries
├── ref-cache.json         # Reference scores, session count, compression metadata
└── archive.md             # Archived entry titles (capped at 500 lines)
```

## Settings Reference

`settings.json.reference` shows the full `~/.claude/settings.json` structure including:
- Hook wiring (PreToolUse for sensitive file guard, PostToolUse for formatting + ref scoring, SessionStart for session init, Stop for tests + auto-capture)
- Status line command
- Enabled plugins (`frontend-design`)
- Cleanup period (set to 3 days; Claude Code default is 30) and attribution config

## Installation

This repo is the canonical source for all Claude Code configuration. The install script adds an `@import` line to your existing `~/.claude/CLAUDE.md` (non-destructive — your customizations are preserved), symlinks other components (hooks, skills, rules, status line) into `~/.claude/`, and auto-merges hook registrations into `~/.claude/settings.json`.

```bash
./install.sh
```

You'll be prompted for each component and for settings.json updates. The installer uses `jq` to merge hook entries from `settings.json.reference` into your existing `~/.claude/settings.json` without clobbering your custom settings (plugins, cleanup period, etc.). Duplicate hook entries are detected and skipped. A backup is created as `settings.json.bak` before any modification. If `jq` is not installed, the settings merge is skipped with a warning.

### Upgrading from symlink-based install

If you previously installed with an older version that symlinked `CLAUDE.md`, running `install.sh` again will automatically migrate: the symlink is removed, your original `CLAUDE.md` is restored from backup, and an `@import` line is added instead.

### Updating

Since hooks, skills, and rules are symlinked (not copied), pulling new changes from the repo takes effect immediately — no re-install needed. The `@import` for `CLAUDE.md` also resolves live from the repo. If a new hook is added, re-run `install.sh` to register it in `settings.json`.

To uninstall, run `./uninstall.sh` — it removes the `@import` line from `CLAUDE.md`, cleans up symlinks, and removes hook/statusline entries from `~/.claude/settings.json`. Your custom settings and original `CLAUDE.md` content are preserved.

See [DEVELOPER.md](DEVELOPER.md) for development setup, testing, and architecture notes.

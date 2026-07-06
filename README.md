# Claude Code Extensions

Custom hooks, skills, rules, and configuration for [Claude Code](https://code.claude.com/docs/en/overview).

Files in this repo are symlinked or copied into `~/.claude/` to extend Claude Code's behavior.

## Structure

```
├── CLAUDE.md                   # Global instructions (@imported into ~/.claude/CLAUDE.md)
├── install.sh                  # POSIX installer (symlink-based) — pick components into ~/.claude/
├── uninstall.sh                # POSIX uninstaller — restore backups or remove symlinks
├── hooks/                      # Event-driven hooks (Python, stdlib only)
│   ├── format-python.py        # PostToolUse: auto-format .py files with ruff + black
│   ├── format_python_mod.py    # Importable module for format-python.py
│   ├── run-tests.py            # Stop: run pytest when Claude finishes responding
│   ├── run_tests_mod.py        # Importable module for run-tests.py
│   ├── session-init.py         # SessionStart: increment session count, log entry count
│   ├── session_init_mod.py     # Importable module for session-init.py
│   ├── auto-capture.py         # SessionEnd: generate entries from git diff at session end
│   ├── auto_capture_mod.py     # Importable module for auto-capture.py
│   ├── sensitive-file-guard.py # PreToolUse: block reads of .env, SSH keys, credentials
│   ├── sensitive_file_guard_mod.py # Importable module for sensitive-file-guard.py
│   ├── statusline.py           # statusLine: user@host:cwd + model + context bar (cross-platform)
│   ├── statusline_mod.py       # Importable module for statusline.py
│   └── lib/                    # Shared Python libraries (stdlib only)
│       ├── entries.py           # Entry parsing/serialization (typed entries, section-aware)
│       ├── fileutil.py          # Atomic writes, safe JSON read/write with .bak fallback
│       ├── paths.py             # Project name and status path resolution
│       ├── scribe.py            # Git diff classification (file type detection, entry generation)
│       └── platformutil.py      # Cross-platform venv (bin/Scripts + .exe) + walk_up helpers
├── skills/                     # Custom slash-command skills (/skill-name)
│   ├── save/                   # /save — checkpoint session progress to status files
│   ├── critical-review/        # /critical-review — parallel subagent plan review
│   ├── implement-batch/        # /implement-batch — parallel subagent batch implementation
│   ├── security-audit/         # /security-audit — parallel subagent security review
│   └── code-review/            # /code-review — parallel subagent code quality review
├── rules/                      # Coding conventions + shared skill fragments
│   ├── python.md               # venv usage, atomic edits around hooks, pathlib, type hints
│   ├── javascript.md           # package manager detection, ES modules, TypeScript prefs
│   ├── shell.md                # $HOME over ~, guard tool availability, pipefail
│   └── review-output-contract.md  # shared verbatim prompt fragments for /code-review + /security-audit
├── tests/                      # Test suite (pytest + shell installer)
└── settings.json.reference     # Reference settings.json
```

## Hooks

### `format-python.py` (PostToolUse)

Runs after every `Edit` or `Write` on `.py` files. Finds `ruff` and `black` in the project's `.venv` (walking up from the edited file, bounded by the git repo root), resolving `.venv/bin` on POSIX or `.venv\Scripts\*.exe` on Windows. Skips formatting if no venv is found or the file is outside a git repo (CWE-427). Runs `ruff check --fix` first (import sorting, auto-fixes), then `black` for final formatting.

### `session-init.py` (SessionStart)

Runs on session startup/resume — and again after a native compaction (`source: "compact"`):
1. Increments `session_count` in `ref-cache.json`
2. Logs an entry count to stderr: "Context: N entries"
3. Re-injects a recency-ordered summary of recent `session-progress.md` entries into the model's context via `additionalContext` (stdout JSON, 4 KB cap). This closes the loop — persisted status returns to the model automatically instead of only being written to disk. Diagnostics stay on stderr so stdout carries exactly one JSON object.

### `auto-capture.py` (SessionEnd)

Runs once at session end. Resolves the project directory (`CLAUDE_PROJECT_DIR`, else cwd) and generates observation entries from uncommitted git changes:
1. Runs `git diff --name-status` to classify changed files (test, config, source, renamed, deleted)
2. Deduplicates against existing entries
3. Appends new observations to a `## Auto-captured` section in `session-progress.md`
4. `/save` later reviews and promotes these entries into the main Completed section

### `run-tests.py` (Stop)

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
| `/critical-review` | Manual | Spawns 4 parallel subagents to review a plan for correctness, edge cases, feasibility, and test coverage. Iterates until no critical/major findings. Logs all accept/reject/defer decisions to `decision-log.md`. |
| `/implement-batch` | Manual | Implements one batch of a plan using parallel subagents per module, then validates with full test suite. Includes complexity gate (flags tasks meeting 2-of-3 thresholds), implementer status protocol (DONE/DONE_WITH_CONCERNS/NEEDS_CONTEXT/BLOCKED), contradiction detection, and cascading-fix escalation (3-strike rule). |
| `/security-audit` | Manual | Spawns 6-7 parallel subagents covering OWASP categories, secrets scanning, CI/CD pipeline security, and web-specific checks. Supports IaC detection, PHP detection, and optional compliance frameworks (PCI-DSS, HIPAA, SOC2, GDPR). Includes CTF-sourced detection patterns, rationalizations-to-reject, red flags, BEFORE/AFTER remediation verification, and follow-up rounds. |
| `/code-review` | Manual | Spawns 5 parallel subagents reviewing architecture, code quality, correctness, performance, and maintainability. Language-aware with idiomatic checks. Includes blast radius risk labeling (HIGH/MED/LOW), mock quality detection, rationalizations-to-reject, red flags, BEFORE/AFTER remediation verification, and follow-up rounds. |

## Rules

Language-specific conventions loaded only when working with matching files (via `paths` frontmatter). Key highlights:

- **Python**: Always use `.venv/bin/python`. Edits must be atomic (imports + usage in one edit) because the format hook runs between edits.
- **JavaScript/TypeScript**: Detect package manager from lock files. ES modules, strict TypeScript, `const` by default.
- **Shell**: `$HOME` not `~`, guard with `command -v`, `set -o pipefail`.

`rules/review-output-contract.md` is not a language rule (no `paths` frontmatter). It is the single source of truth for the boilerplate prompt fragments shared verbatim between `/code-review` and `/security-audit`; each skill reads it and inlines the fragments at marked points. The severity scale, field list, rationalizations, and red flags stay per-skill (they differ by domain).

## Status Line

`hooks/statusline.py` renders a PS1-style prompt in the Claude Code UI:

```
user@host:~/project (Opus 4.8) [████████░░ 80%] ~$1.23
```

- Green/yellow/red context bar based on remaining context window
- Model name (with "Claude " prefix stripped for brevity)
- Thresholds shifted +10% to compensate for underreported usage
- Cost estimate (`~$X.XX`) — the `~` prefix indicates this is an approximate API-equivalent cost, not an actual charge. Claude Code reports `total_cost_usd` even on Pro/Max subscriptions as a usage-equivalent metric. Suppressed when $0.00.

## Context Persistence

The hooks and skills above form a context persistence system that helps Claude maintain awareness across sessions. The system works automatically once hooks are activated:

1. **Auto-capture** (`auto-capture.py`): At session end (`SessionEnd`), uncommitted git changes are classified and appended as observation entries.
2. **Manual save** (`/save`): Claude writes typed entries (decisions with sacred `Why:` text, observations) and promotes auto-captured entries.
3. **Re-injection** (`session-init.py`): On session start/resume and after a native compaction, a recency summary of recent entries is injected back into the model's context (`additionalContext`, 4 KB cap) — closing the loop so persisted state is actually re-read, not just written.

Native context compaction (built into Claude Code) summarizes the live conversation; these hooks persist work-progress state to disk and re-inject it so it survives across sessions and compactions. Decision `Why:` text written by `/save` is preserved verbatim.

### Status files

```
~/.claude/status/<project>/
├── session-progress.md    # Current session entries
├── project-status.md      # Cumulative project history
└── ref-cache.json         # Session count + last-updated timestamp
```

## Settings Reference

`settings.json.reference` shows the full `~/.claude/settings.json` structure including:
- Hook wiring (PreToolUse for sensitive file guard, PostToolUse for formatting, SessionStart for session init, Stop for tests, SessionEnd for auto-capture)
- Status line command
- Enabled plugins (`frontend-design`)
- Cleanup period (set to 3 days; Claude Code default is 30) and attribution config

## Installation

This repo is the canonical source for all Claude Code configuration, installed via `install.sh` (symlink-based, macOS / Linux). Windows users: see [Windows](#windows) below.

The install script adds an `@import` line to your existing `~/.claude/CLAUDE.md` (non-destructive — your customizations are preserved), symlinks other components (hooks, skills, rules, status line) into `~/.claude/`, and auto-merges hook registrations into `~/.claude/settings.json`.

```bash
./install.sh
```

You'll be prompted for each component and for settings.json updates. The installer uses `jq` to merge hook entries from `settings.json.reference` into your existing `~/.claude/settings.json` without clobbering your custom settings (plugins, cleanup period, etc.). A backup is created as `settings.json.bak` before any modification. If `jq` is not installed, the settings merge is skipped with a warning.

### Upgrading

`install.sh` doubles as an upgrade command. Running it on an existing install will:

- **Skip already-installed components** — symlinks pointing to the correct source are detected and skipped without prompting.
- **Offer new components** — hooks, skills, or rules added since your last install are prompted for installation.
- **Clean up stale symlinks** — if a component was removed or renamed in the repo, broken symlinks in `~/.claude/` are detected and offered for removal.
- **Replace stale settings.json entries** — all repo-managed hook entries (commands referencing `/.claude/hooks/`) are stripped and re-added from the current reference. This handles renamed hooks, changed command formats, and removed hooks. User hooks are preserved.
- **Deduplicate settings.json** — duplicate hook entries left by older installer versions are collapsed.
- **Update repo-managed statusLine** — if the statusLine references our script, it's updated to match the current reference. Custom statusLine configurations are preserved.
- **Migrate old CLAUDE.md symlinks** — older versions symlinked `CLAUDE.md` directly; running `install.sh` again replaces the symlink with an `@import`, restoring your original content from backup.

When everything is already current, the installer reports "already installed — skipping" for each component and exits without prompting.

### Updating

Since hooks, skills, and rules are symlinked (not copied), pulling new changes from the repo takes effect immediately — no re-install needed. The `@import` for `CLAUDE.md` also resolves live from the repo. Re-run `install.sh` after pulling only when new components are added or hook registrations change.

### Uninstalling

Run `./uninstall.sh` — it discovers all symlinks in `~/.claude/` pointing into the repo, removes the `@import` block from `CLAUDE.md`, cleans up hook/statusline entries from `settings.json`, and offers to remove orphaned `.bak` files. Your custom settings and original `CLAUDE.md` content are preserved.

## Windows

There is **no native-Windows installer** (`install.sh` / `uninstall.sh` are bash and the settings merge uses `jq`). Both Windows surfaces are supported, but only the CLI path is automated. The runtime hooks are cross-platform Python (they resolve `.venv\Scripts\*.exe` and guard POSIX-only `chmod`), so once wired up they run correctly on either.

### Claude Code CLI — via WSL2 (automated)

Run the CLI inside WSL2 and install exactly as on Linux:

1. **Install WSL2** (once, from an admin PowerShell): `wsl --install`, then reboot and open your Linux distro (Ubuntu by default).
2. **Inside the WSL2 shell**, install Claude Code and the prerequisites (`git`, `python3`, `jq`), then clone this repo *into the WSL2 filesystem* (e.g. `~/claude_extensions`, not `/mnt/c/...` — avoid the Windows drive mount for speed and correct permissions).
3. **Run the installer** from the repo: `./install.sh`.
4. **Use Claude Code from the WSL2 shell** — the CLI directly, or VS Code with the *WSL* remote extension. Config lives in the WSL2 home (`~/.claude/`), separate from the native-Windows `%USERPROFILE%\.claude\`.

### Claude desktop app (Code tab) — native Windows (manual)

The desktop app's **Code** tab runs Claude Code natively on Windows and [shares the same config as the CLI](https://code.claude.com/docs/en/settings) — it reads `%USERPROFILE%\.claude\` (`settings.json`, `CLAUDE.md`, `skills/`, `rules/`) and **does execute hooks**, run under **Git Bash** (which the app requires you to install on first launch). It *cannot* operate on a WSL2 project locally (its environments are Local, cloud Remote, and SSH only), so the WSL2 install above does **not** cover it.

With no installer, wire it up by hand:

1. Install **[Git for Windows](https://git-scm.com/downloads/win)** (the app requires it) — this provides the Git Bash shell that runs the hooks.
2. **Copy** this repo's `hooks/`, `skills/`, and `rules/` into `%USERPROFILE%\.claude\`. No symlinks on Windows, so re-copy after each `git pull`.
3. Add the import line to `%USERPROFILE%\.claude\CLAUDE.md` (create it if absent): `@C:/path/to/claude_extensions/CLAUDE.md`.
4. Merge the hook and `statusLine` entries from `settings.json.reference` into `%USERPROFILE%\.claude\settings.json`. Keep the forward-slash `$HOME/...` paths (Git Bash expands them), but **replace `python3`** with an interpreter that exists on your machine — `python`, the `py` launcher, or a full `C:/path/to/python.exe` — because `python3` is often not on `PATH` in Git Bash on Windows.

See [DEVELOPER.md](DEVELOPER.md) for development setup, testing, and architecture notes.

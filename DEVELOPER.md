# Developer Guide

## Setup

Python hooks use stdlib only — no external dependencies at runtime. For development and testing:

```bash
python3 -m venv .venv
.venv/bin/pip install pytest ruff
```

## Testing

```bash
.venv/bin/pytest              # Python tests (296 tests)
.venv/bin/ruff check .        # lint
bash tests/test_install.sh    # installer/uninstaller tests (91 tests)
bash tests/test_statusline.sh # status line tests (27 tests)
```

Python tests live in `tests/` and cover all modules in `hooks/lib/` and the hook entry points. Shell tests are standalone bash scripts with built-in assertion helpers.

## Architecture

### Hook script pattern

Python hook scripts use hyphenated filenames (`session-init.py`, `auto-capture.py`, `sensitive-file-guard.py`) to match shell hook naming conventions. Since Python can't import hyphenated names, each has a `_mod.py` companion:

```
session-init.py      → imports from session_init_mod.py
auto-capture.py      → imports from auto_capture_mod.py
```

The thin entry-point scripts just inject `sys.path` and call `main()` from the companion module. All logic and tests target the `_mod.py` files.

### Import conventions

Modules in `hooks/lib/` use `from lib.X import ...` (not `from hooks.lib.X`). This works because hook entry points inject `hooks/` into `sys.path` via:

```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
```

Test files add both the project root and `hooks/` to `sys.path`:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
```

### Atomic edits (ruff interaction)

A PostToolUse hook runs `ruff --fix` + `black` after every `Edit`/`Write` on `.py` files. This means edits must be self-consistent — never add an import in one edit and its usage in a later edit, because ruff will remove the "unused" import in between. Combine imports with their first usage in a single edit.

### Shared libraries

All shared code lives in `hooks/lib/` — stdlib only, no external dependencies:

| Module | Purpose |
|--------|---------|
| `entries.py` | `Entry` dataclass, typed entry parsing/serialization, section-aware `session-progress.md` parsing |
| `fileutil.py` | Atomic writes (`tempfile` + `os.replace`), safe JSON read/write with `.bak` fallback |
| `paths.py` | Project name resolution (git remote → git root → cwd), status directory paths |
| `scribe.py` | Git diff classification, observation entry generation |

### Context persistence data flow

```
Session end → auto-capture.py → appends ## Auto-captured entries
                                    ↓
/save → Claude promotes entries → session-progress.md (typed entries)
                                    ↓
Session start/compact → session-init.py → increments session_count + re-injects recency summary (additionalContext)
```

### Install mechanism

`install.sh` and `uninstall.sh` both support `--source-only` to allow tests to source guard functions without executing the installer:

```bash
source install.sh --source-only   # exports resolve_path, check_overlap, merge_settings_json, etc.
source uninstall.sh --source-only  # exports link_points_to_repo, uninstall_claude_md_import, etc.
```

**CLAUDE.md** uses `@import` (not symlink) — the installer prepends a 3-line block with HTML comment markers to `~/.claude/CLAUDE.md`:

```
<!-- claude-extensions:import -->
@/path/to/repo/CLAUDE.md
<!-- /claude-extensions:import -->
```

This preserves user customizations. The uninstaller removes only the marked block via sed. Old symlink-based installs are automatically detected and migrated.

**All other components** (hooks, skills, rules, statusline) are symlinked from `~/.claude/` into the repo, so `git pull` updates them in place.

**Upgrade support** — `install.sh` is designed to be re-run after pulling new versions:

- Already-installed symlinks are detected (raw and resolved path comparison) and skipped without prompting
- Broken symlinks pointing into the repo (from removed/renamed components) are detected and offered for removal
- Settings.json entries are stripped and re-added from the current reference on every run, so stale entries are cleaned up automatically
- When everything is current, the installer produces no interactive prompts

### Hook registration

Hooks are registered in `settings.json.reference` and merged into `~/.claude/settings.json` by `install.sh`. The merge is handled by `merge_settings_json()` which:

1. **Strips** all existing repo-managed entries (commands containing `/.claude/hooks/`)
2. **Adds** all entries from the current reference
3. **Deduplicates** within each hook type as a safety net

This strip-then-add approach ensures upgrades cleanly replace stale entries (renamed hooks, changed command formats, removed hooks) while preserving user hooks.

| Event | Hook | Timeout |
|-------|------|---------|
| PreToolUse (Read) | `sensitive-file-guard.py` | 5s |
| PreToolUse (Bash) | `sensitive-file-guard.py` | 5s |
| PostToolUse (Edit\|Write) | `format-python.sh` | default |
| SessionStart | `session-init.py` | 10s |
| Stop | `run-tests.sh` | 120s |
| SessionEnd | `auto-capture.py` | 10s |

### Subagent model selection in review skills

The multi-agent skills no longer pin a model per spawned subagent. Every subagent runs on the **latest, most capable model available**: the skills omit the Agent tool's `model` parameter so each subagent inherits the session's model rather than naming a version-specific model (which gets discontinued — e.g. `fable`). They must not be downgraded to a cheaper tier: breadth slots dropped `sonnet` after a measured comparison (2026-06-11) where its false-positive rate cost more main-session verification time than the model savings, and `haiku` is never a default — these prompts require rejecting rationalizations and careful reading, where it is materially weaker.

| Skill | Subagent model |
|-------|----------------|
| `/code-review` | latest model, inherited (all 5 agents + both follow-up agents) |
| `/security-audit` | latest model, inherited (all 7 agents + both follow-up agents) |
| `/critical-review` | latest model, inherited (all four Round-1 agents + both follow-up agents) |
| `/implement-batch` | latest model, inherited (all implementers) |

Synthesis runs in the main session, so it already uses whatever model the session runs (no `model` param to set). Setting `CLAUDE_CODE_SUBAGENT_MODEL` in the environment Claude launches subagents under overrides the inherited model for every subagent above.

### Shared review output-contract fragments

`rules/review-output-contract.md` is the single source of truth for the boilerplate that is **identical verbatim** between the `/code-review` and `/security-audit` subagent prompts: the scope/context opening, the findings-list-format transition, and the closing instruction. Each skill's Section 2 reads the file and inlines the named fragment at each `<<shared:…>>` marker. The skills reference it by its **installed** path `~/.claude/rules/review-output-contract.md` (symlinked there by `install.sh`'s `rules/*.md` discovery, like every other rule) so the runtime Read resolves regardless of the project CWD — a bare `rules/…` relative path would only resolve when the CWD happens to be this repo. No installer change was needed; the glob picks the file up and `uninstall.sh`'s generic symlink sweep removes it.

Only those three fragments are shared. The **field list**, **severity scale**, **"Rationalizations to Reject"**, and **"Red Flags"** are domain-specific (code review vs. security) and stay inline per skill — consolidating them would have dropped the per-domain tuning. `/critical-review` reviews a plan rather than code, so its preamble and closer differ and it does not consume the fragments. `tests/test_review_contract.py` pins this contract (shared file has no severity scale; consumers reference it, use the markers, no longer inline the fragments, and keep their own scale/rationalizations).

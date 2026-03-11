# Changelog

All notable changes to this project will be documented in this file.

## [0.3] - 2026-03-10

### Added

- **Shell test suites** — `tests/test_install.sh` (48 tests) and `tests/test_statusline.sh` (27 tests) covering installer, uninstaller, and status line
- `tests/test_format_python.py` — unit tests for format-python.sh venv resolution

### Changed

- **CLAUDE.md install switched from symlink to `@import`** — `install.sh` now prepends an `@import` line to `~/.claude/CLAUDE.md` instead of replacing it with a symlink. User customizations are preserved. Old symlink installs are automatically migrated on re-run.
- `uninstall.sh` — restructured into `main()` function with `--source-only` guard for testability; removes `@import` block via sed; fixed `link_points_to_repo` prefix-match bug (`"$REPO_DIR/"*` not `"$REPO_DIR"*`)
- `install.sh` — added `--source-only` guard, `upgrade_claude_md_symlink()`, `install_claude_md_import()` with HTML comment markers for idempotent import management
- `statusline-command.sh` — cost display changed from `$X.XX` to `~$X.XX` to indicate API-equivalent estimate
- `README.md` — rewritten installation section for @import approach, added upgrade guide, documented cost estimate semantics, added DEVELOPER.md link
- `settings.json.reference` — documented all hook timeouts and event matchers
- **Skill frontmatter** — all 5 skills updated with `name`, `description`, and `argument-hint` fields
- **Rules** — `python.md`, `javascript.md`, `shell.md` updated with project-specific conventions
- `/security-audit` — Agent 5 now recommends `.pre-commit-config.yaml` with `gitleaks` when no secrets scanning tooling is found

### Security

- `hooks/format-python.sh` — quote all variable expansions to prevent word splitting (CWE-78)
- `hooks/lib/ref_tracker.py` — bounded keyword set size, reject non-string/non-finite score values
- `hooks/lib/fileutil.py` — validate JSON decode returns dict before use
- `hooks/lib/paths.py` — additional traversal guards on project name sanitization
- `.gitignore` — added `*.bak` to prevent backup files from being tracked

## [0.2] - 2026-03-09

### Added

- **Context persistence system** — hooks and libraries for maintaining awareness across sessions
  - `hooks/lib/entries.py` — typed entry parsing/serialization (decision/observation with IDs)
  - `hooks/lib/fileutil.py` — atomic writes and safe JSON read/write with `.bak` fallback
  - `hooks/lib/ref_tracker.py` — 3-tier reference scoring (path match, directory overlap, keyword overlap)
  - `hooks/lib/paths.py` — project name resolution from git remote/root/cwd
  - `hooks/lib/scribe.py` — git diff classification and observation generation
  - `hooks/lib/compressor.py` — 4-tier context compression (Active → Compressed → Archived → Dropped)
- **New hooks**
  - `ref-scorer.py` (PostToolUse) — scores status entries against tool context
  - `session-init.py` (SessionStart) — increments session count, checks compression triggers
  - `auto-capture.py` (Stop) — generates observation entries from uncommitted git changes
- **New skills**
  - `/compress` — force context compression on demand, bypassing automatic thresholds
- **Test suite** — 285 tests covering all libraries and hooks
- `.gitignore` with comprehensive coverage (secrets, AI tools, credentials, OS artifacts, build dirs)
- `DEVELOPER.md` — development setup and architecture guide

### Changed

- `skills/save/SKILL.md` — typed entry format with decision/observation classification and unique IDs
- `install.sh` — extended hook discovery to `hooks/*.{sh,py}`
- `settings.json.reference` — added hook wiring for ref-scorer, session-init, and auto-capture
- `README.md` — full documentation of context persistence system, updating section

### Security

- `hooks/format-python.sh` — removed PATH fallback for `ruff`/`black`; venv-only resolution (CWE-427)
- `hooks/run-tests.sh` — removed PATH fallback for `pytest`; venv-only resolution (CWE-427)
- `hooks/lib/paths.py` — sanitized project name to prevent path traversal (CWE-22); status dirs created with mode 0700 (CWE-276)
- `hooks/lib/fileutil.py` — temp files set to mode 0600 before replace (CWE-276); error messages use basename only (CWE-209)
- `hooks/ref_scorer_mod.py` — 1MB stdin read limit (CWE-400)
- Hook entry points now log exception types to stderr instead of silently swallowing

## [0.1] - 2026-03-07

### Added

- Initial release with existing extensions
- `CLAUDE.md` — global instructions for Claude Code
- `hooks/format-python.sh` — PostToolUse hook for auto-formatting Python with ruff + black
- `hooks/run-tests.sh` — Stop hook for running pytest after Claude responds
- `statusline-command.sh` — PS1-style status line with context window bar
- **Skills**: `/save`, `/critical-review`, `/implement-batch`, `/security-audit`
- **Rules**: `python.md`, `javascript.md`, `shell.md`
- `settings.json.reference` — reference configuration for `~/.claude/settings.json`
- `install.sh` / `uninstall.sh` — interactive symlink-based installer and uninstaller

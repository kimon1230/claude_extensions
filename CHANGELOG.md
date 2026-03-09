# Changelog

All notable changes to this project will be documented in this file.

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

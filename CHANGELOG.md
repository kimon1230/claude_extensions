# Changelog

All notable changes to this project will be documented in this file.

## [0.5] - 2026-03-27

### Added

- **`sensitive-file-guard.py` (PreToolUse hook)** — blocks reads of `.env`, SSH keys, credentials, AWS configs, and package tokens. Intercepts both `Read` tool and `Bash` commands via `shlex.split()` tokenization. Case-insensitive basename matching with explicit allowlists (`.env.example`, `.envrc`). `*.key` requires keyword guard to avoid false positives. 83 tests.
- **Output Contracts** for `/code-review`, `/critical-review`, `/security-audit` — each skill now defines the required structure of its final synthesized report (findings table, aggregate counts, verdict, remediation offer).
- **Rationalizations to Reject** — 9 security dismissals injected into `/security-audit` subagent prompts ("It's behind a VPN", "Only admins can reach this", etc.) and 6 code quality dismissals into `/code-review`.
- **Red Flags** — thought-pattern watchlists injected into `/security-audit` (5 items) and `/code-review` (5 items) targeting the agent's own corner-cutting impulses.
- **CTF-sourced detection patterns** for `/security-audit` — PHP attack surface (gated behind `php_detected` flag), encoding/parsing mismatches (Unicode normalization, Shift-JIS, U+00A0), Go `len()` byte/rune confusion, prototype pollution, JWE token handling, auth race conditions, deserialization depth (XMLDecoder, Castor XML, pickle, PHP serialization), SSRF-to-Docker/gopher, CSP bypass taxonomy, DOM clobbering, behavioral framework XSS narrowing.
- **Implementer status protocol** for `/implement-batch` — subagents report `STATUS: DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, or `BLOCKED`. Main session handles each status with defined escalation paths.
- **Contradiction detection** for `/implement-batch` — scans subagent output for phrases like "requires manual", "should work", "TODO" alongside success claims. Catches the "claims done but admits failure" pattern.
- **Cascading-fix escalation** for `/implement-batch` — 3-strike rule. If fixes keep breaking previously-passing modules, stop and flag as architectural issue.
- **Complexity gate** for `/implement-batch` — flags tasks meeting 2-of-3 conditions (>5 files, >3 acceptance criteria, cross-module dependencies) before spawning subagents. Soft gate — user can override.
- **Decision logging** for `/critical-review` — appends accept/reject/defer decisions to `decision-log.md` with rationale. Triggers on all user response paths.
- **Task Delivery States** in `CLAUDE.md` — mental model for task progression (intake → planning → executing → validating → reviewing → done / blocked).
- **Subagent context isolation rule** in `CLAUDE.md` — always paste full task text into subagent prompts, never make subagents read plan files.
- **Blast radius risk labeling** for `/code-review` — findings include `Risk: HIGH|MED|LOW` based on structural heuristics. Secondary sort by risk within same severity.
- **Mock quality detection** for `/code-review` — Agent 5 now flags mock-heavy tests (3:1 ratio), missing real module imports, behavioral-only assertions, and over-mocked integration tests.
- **BEFORE/AFTER remediation verification** for `/code-review` and `/security-audit` — records failing state before fix, verifies passing state after. Uses function/symbol anchors for non-testable findings.

### Changed

- **Skill descriptions** — all 6 skills rewritten for CSO compliance (trigger conditions only, no workflow summaries). Prevents Claude from shortcutting skill bodies.
- **Skill frontmatter** — all 6 skills now include `risk: safe|critical` field and optional `risk-note`.
- **Rules frontmatter** — `python.md`, `javascript.md`, `shell.md` now include `paths` frontmatter for file-type-specific loading.
- **`/implement-batch` step 4** — split into 4 (triage: status + contradiction), 4b (consistency review), 4c (validation).
- **`/implement-batch` step 7** — phase gate: recommends new session for batch ≥ 3.
- **`/critical-review`** — renumbered to 8 steps (decision logging is step 5; non-approval path explicitly logs rejections).
- **`CLAUDE.md` Code Quality** — overloaded paragraph broken into sub-bullets.
- **`CLAUDE.md` Planning** — batch numbering convention: always start at 1, never 0.
- **`install.sh`** — new `install_settings()` function: `jq`-based merge of hooks and statusLine from `settings.json.reference` into `~/.claude/settings.json`. Deduplicates by (matcher, commands) tuple. Backs up before modifying. Replaces the old "go read settings.json.reference" manual step.
- **`uninstall.sh`** — new `uninstall_settings()` function: removes hook entries pointing to `/.claude/hooks/` and statusLine from `~/.claude/settings.json`. Replaces old manual reminder.
- **`settings.json.reference`** — added `PreToolUse` section for sensitive-file-guard (Read + Bash matchers).
- **`/security-audit` synthesis** — now reports `php_detected` status alongside `web_app` and `iac_detected`.

## [0.4] - 2026-03-13

### Added

- **`/code-review` skill** — parallel subagent code quality review from a senior distinguished engineer's perspective. 5 agents with explicit non-overlapping boundaries: Architecture & Design, Code Quality & Readability, Correctness & Robustness, Performance & Efficiency, Maintainability & Testing. Language-aware with idiomatic checks for Python, JS/TS, Go, Rust, and Java. Reads project rule files (`rules/<language>.md`) for project-specific conventions.

### Changed

- **`/security-audit` — 5 improvements from external security engineer analysis:**
  - **Threat context** (new Section 1 subsection): main session examines up to 10 files to identify trust boundaries, data sensitivity, and high-risk components before spawning agents. Relevant context subsets composed into each agent's prompt.
  - **Agent 7 — CI/CD Pipeline Security** (new always-on agent): checks for SAST (Semgrep, CodeQL), SCA (Trivy, Snyk, Dependabot), and DAST tooling in CI configs. Delineated from Agent 5 (secrets vs. tooling presence).
  - **IaC security review**: detects Terraform, CloudFormation, Pulumi, Kubernetes, and Helm files. Adds conditional checks to Agent 4 (IAM policies, public exposure, encryption gaps, hardcoded values, K8s misconfigs) with increased finding limit (max 15).
  - **Compliance context** (optional): `compliance: pci-dss|hipaa|soc2|gdpr` parameter adds framework-specific checks distributed as conditional blocks across relevant agents. Includes disclaimer in synthesis.
  - **Quantified impact**: verbatim template now instructs agents to quantify blast radius from code context.
- **`/security-audit` scope** — removed artificial 30-file cap for entire-project reviews; agents now review all source files with intelligent distribution by domain relevance
- **`/code-review` scope** — same: no artificial file cap, full project coverage with prioritization by architectural significance

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

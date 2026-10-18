# Changelog

All notable changes to this project will be documented in this file.

## [0.10]

**Existing installs:** re-run `install.sh` to pick up the new `Grep` matcher and the `git-guard` hook (re-merges `settings.json`). If `~/.claude/skills`, `hooks`, or `rules` are whole-directory symlinks into the repo (very early installs), migrate them first as described in README **Upgrading**.

### Security

- **`sensitive-file-guard` now intercepts the `Grep` tool** — previously it matched only `Read` and `Bash`, leaving a bypass: the `Grep` tool with `output_mode: "content"` can print file contents, so `Grep(pattern, path=".env")` read secrets straight past the guard. Added a `Grep` matcher in `settings.json.reference` and `_check_grep_tool()`. The concrete `path` is matched as a path; the `glob` is matched **glob-aware** via `_glob_targets_sensitive()`, which keys on each family's *distinctive* token so it blocks the wildcarded form of every protected pattern (`.env*`, `*.env`, `secret*`, `credential*`, `id_*`, `*.pem`/`*.p*`, brace forms like `*.{pem,p12}`, and anything under a `.aws`/`.ssh` directory) without over-blocking catch-alls (`*`, `**/*`, `src/**`, `*.*`, which carry no distinctive token and are treated like no glob; dotfile and `?` forms like `.*` and `*.???`, and env globs that never spell out `.env` (`.e*`, `?env`, `.e*.local`), still select secrets and stay blocked; a glob over 256 characters or with more than 64 brace alternatives is denied outright) or common stems — `server.*`, `*.local`, `tls.*`, and bare `*.key` stay allowed, mirroring the guard's existing low-false-positive policy (it already allows `*.key`/`translation.key` for Read; a concrete `server.key` is still caught by `_is_sensitive`). Two rounds of adversarial review shaped this: the first found the initial glob check reused concrete-path logic (bypass on `.env*` etc.); the second found the naive fix over-blocked common stems (`server.*` → would refuse a normal `grep --glob server.*`). The `pattern` is a regex, not a path, so it is not checked. A Grep `path` inside `.aws/` or `.ssh/` (or naming the directory itself) is blocked too. The Bash check now joins backslash-newline continuations first, so `cat \` + newline + `.env` is caught. **Residual, documented gap:** a content-mode Grep scoped only to a directory/cwd with no sensitive `glob` cannot be classified by filename and is not blocked — inherent to any name-based filter. Since that gap already exposes every file a glob could select, the glob check targets the forms a cooperative model naturally writes; deliberately crafted spellings (backslash escapes, odd wildcard fragments) fall under the same gap.
- **PreToolUse deny migrated to the documented contract** — the guard now emits `hookSpecificOutput.permissionDecision: "deny"` (with `permissionDecisionReason`) instead of the legacy top-level `{"decision": "block"}`, which is undocumented for `PreToolUse`. The legacy form still works in current Claude Code (verified live), so this is future-proofing the security control against a release dropping it; one change covers the `Read`/`Bash`/`Grep` emit site.
- **New `git-guard` hook denies in-session `git commit`/`git push`** — turns the "user handles all git" rule from a CLAUDE.md request into hook enforcement (docs: must-happen-every-time rules belong in a `PreToolUse` hook; a deny is honored even under `bypassPermissions`). `git_guard_mod.py` joins backslash-newline continuations, tokenizes the `Bash` command with `shlex`, flattens unspaced shell operators and redirects (so `git push;echo` and `git push>/dev/null` are caught), and matches the git launcher (incl. `git.exe`, `sudo git`, env-prefix, absolute path) plus a blocked subcommand, correctly skipping global options (`git -C /path commit`) and never misfiring on a blocked word used as an argument (`git stash push`, `git log commit` stay allowed). Registered as a second command on the existing `Bash` matcher. It ships with a second layer: `permissions.deny` rules `Bash(git commit *)` / `Bash(git push *)` in the settings, which Claude Code applies to nested subcommands (subshells, `$(…)`, loop bodies), git-guard's gaps. git-guard in turn catches the forms those rules miss (`git -C . push`, `/usr/bin/git push`, `git 'push'`). The installer appends them to any existing deny rules, and the uninstaller removes exactly those two. It is a guardrail against the *cooperative* model's accidental commits/pushes, **not** an adversarial control — shell nesting (`bash -c`), command substitution, variable indirection, aliases, and malformed (fail-open) input are documented accepted residual gaps. Plan critical-reviewed to convergence (2 rounds, clean); the review empirically caught the unspaced-operator bug the final design fixes.

### Changed

- **`CLAUDE.md` Shell Commands section**: read commands must take literal absolute paths (no `~`, `$VAR`, `$(...)`, globs, or `cd dir && …`), and `sed` is limited to a plain numeric `sed -n 'N,Mp'` (no `sed -i`, no regex ranges). Paths computed at run time can't be checked against `blockReadsOutsideWorkingDirectories`, so each such command used to trigger a manual approval prompt. Subagent prompts must carry the same rules.
- **`CLAUDE.md` mutation-check rule**: a mutation test must prove the mutation was applied, either via the Edit tool (which errors on no match) or a `git diff --quiet` guard after a scripted edit, and must be reverted to an empty diff afterwards. A passing test against an unmutated file proves nothing.
- **Skill descriptions rewritten for auto-selection**: all five skills now use third-person descriptions that name what the skill does and when to use it. The descriptions of the two auto-invoked review skills now include domain trigger terms (e.g. injection, SSRF, secrets for `/security-audit`). `/security-audit` also had its "Security Review" heading and scope prompt renamed to "Security Audit", and its pinned gitleaks example version is annotated.
- **Statusline `[EXT]` now fires from `exceeds_200k_tokens`** instead of `context_window.context_window_size > 200000`. The old source was a static model capability, so on 1M-context models (e.g. Opus 4.8) the tag was always lit and conveyed nothing; the new source lights it only once actual usage crosses the fixed 200k threshold where extended-context pricing/behavior applies.

### Added

- **Statusline subscription rate-limit segment** — renders `5h:N% 7d:N%` from `rate_limits.{five_hour,seven_day}.used_percentage` (present only for Claude.ai Pro/Max sessions after the first API response). Each window is colored by its own usage (dim / yellow ≥75% / red ≥90%); absent windows are omitted. At 75% or above a window also shows a countdown to its `resets_at`, e.g. `5h:92%→2h13m`.
- **Statusline reasoning-effort level** — the model segment now appends the live effort level from `effort.level` (`low`/`medium`/`high`/`xhigh`/`max`), e.g. `(Opus 5 high)`, reflecting mid-session `/effort` changes. Only the documented levels render; the field is omitted for models that don't expose the effort parameter, so nothing shows there.
- **Statusline open-PR status** — renders `PR#<n> <state>` from `pr.number`/`pr.review_state` while an open PR exists for the current branch, colored by review state (green `approved` / red `changes` / yellow `pending` / dim `draft`). The number renders alone when the review state is absent; the whole segment is omitted when there is no open PR.

### Fixed

- **Declining a hook in `install.sh` no longer blocks tools**: the settings merge registered every reference hook, even ones the user declined, and a registered but missing script exits 2, which Claude Code treats as a blocking error. Declining `sensitive-file-guard.py` denied every Read/Bash/Grep call, and declining `git-guard.py` would deny every Bash call. Only hooks whose script is installed in `~/.claude/hooks/` are now registered (fresh installs included), and a repo-managed `statusLine` is dropped when `statusline.py` isn't installed. A hook's `*_mod.py` module is no longer prompted for separately; it is linked together with its entry script.
- **Re-running `install.sh` with everything installed now updates `settings.json`**: it used to exit as soon as no new component was selected, skipping the stale-link cleanup and the settings merge, so a release that only changed hook registrations never reached an existing install.
- **Statusline no longer shows a sibling of the home directory as `~`**: with home `/home/kim`, a cwd of `/home/kim2/x` rendered as `~2/x`. Also, a non-finite context percentage (JSON `1e999`) raised `OverflowError` and blanked the whole line instead of dropping only the context segment.
- **Claude Code's auto-synced skills no longer leak into the repo**: on installs where `~/.claude/skills` is a legacy whole-directory symlink into the repo, Claude Code writes its synced skill bundle to `skills/synced/` in the working tree, where it fails `ruff check .` and shows up as an installable skill. `skills/synced/` is now gitignored (as is `.ruff_cache/`), and `install.sh` skill discovery skips any directory without a `SKILL.md`. The README **Upgrading** section documents migrating off the directory-symlink layout.
- **`rules/review-output-contract.md` no longer loads into every session** — it lives under `rules/` (to get symlinked to a stable `~/.claude/rules/` path the review skills `Read`), but a rule with no `paths` frontmatter loads unconditionally at CLAUDE.md priority, so its ~40 lines of meta-documentation were consuming context in every session for no behavioral benefit. Added a deliberately never-matching `paths:` scope so it stays symlinked and on-demand-readable but never auto-loads.

## [0.9]

### Changed

- **Runtime hooks ported to cross-platform Python** — the three remaining shell hooks are now Python: `statusline.py` (was `statusline-command.sh`), `format-python.py` (was `format-python.sh`), and `run-tests.py` (was `run-tests.sh`). The entire runtime hook surface is now Python (stdlib only) — this drops the `jq` dependency from `format-python`, adds unit-test coverage the shell versions lacked, and runs under any shell (including Git Bash on Windows and WSL2). New `hooks/lib/platformutil.py` resolves `.venv/bin` vs `.venv\Scripts\*.exe` and walks parent directories safely across platforms; `hooks/lib/fileutil.py` guards its `os.chmod` calls behind `os.name != "nt"` (POSIX permission bits don't apply on Windows).

### Added

- **Windows setup guidance** — the README `## Windows` section documents two paths: the **CLI** via WSL2 + `install.sh` (automated, identical to Linux), and the desktop app's **Code tab** running natively on Windows (which shares `%USERPROFILE%\.claude\` config with the CLI and executes hooks under Git Bash) via a manual copy + `settings.json` merge. There is no native-Windows installer; `install.sh` / `uninstall.sh` remain POSIX/bash.

## [0.8]

### Changed

- **Multi-agent skills stop pinning a model name** — `/code-review`, `/security-audit`, `/critical-review`, and `/implement-batch` no longer name `fable`, `opus`, or any version-specific model per subagent. They now spawn every subagent on the latest, most capable model by omitting the Agent tool's `model` override so each inherits the session's model, sidestepping discontinued-model churn (e.g. Fable). The guardrails are retained as cautions rather than pins: don't downgrade breadth/review passes to `sonnet` (per the 2026-06-11 comparison) and never default to `haiku`. `/implement-batch` previously kept an `opus`/`sonnet` cost split; that is collapsed to the inherited model as well. DEVELOPER.md mapping table updated.
- `README.md` statusline example model label `Opus 4.7 → Opus 4.8`.

## [0.7] - 2026-06-11

### Changed

- **Review-skill model ladder raised one tier for Fable 5** — `/code-review`, `/security-audit`, and `/critical-review` now spawn the high-stakes passes (architecture, correctness, injection/auth/crypto, all `/critical-review` agents, all fix-verification agents) with `fable` and the breadth passes with `opus` (previously `opus`/`sonnet`). Breadth slots dropped `sonnet` after a 2026-06-11 comparison showed its false-positive rate cost more main-session verification time than it saved. `/implement-batch` is unchanged (`opus` implementers, `sonnet` for mechanical modules — tests gate its output). DEVELOPER.md mapping table updated.

## [0.6]

Harness modernization for current Claude Code (CLI 2.1.x). All 6 batches implemented and validated. Plan: `~/.claude/plans/claude_extensions/harness-modernization-20260527.md`.

**Existing installs:** re-run `install.sh` to pick up the hook-wiring change (re-merges `settings.json` — moves auto-capture to `SessionEnd`, drops the removed `ref-scorer` hook — and cleans up symlinks from removed components).

### Added

- **`session-init.py` re-injects persisted context** on session start/resume and after native compaction (`source: "compact"`) — emits a recency-ordered summary of recent `session-progress.md` entries via `additionalContext` (stdout JSON, 4 KB cap, source-gated; diagnostics stay on stderr). Closes the write-only loop so persisted status returns to the model automatically instead of only being written to disk. No `UserPromptSubmit` fallback needed (Batch 1 validated that `SessionStart` re-fires on compaction).

### Removed

- **Context-compression subsystem** — deleted `hooks/lib/compressor.py` (4-tier Active→Compressed→Archived→Dropped rotation), the `/compress` skill, the `ref-scorer.py` PostToolUse hook + `ref_scorer_mod.py`, and `hooks/lib/ref_tracker.py`. An audit found the compressor had **never fired in 29 sessions** (no `last_compression` key, no `archive.md`, no `## Compressed Context` section) and its tiers were write-only; native context compaction now summarizes the live conversation. Removed the `ref-scorer` entry from `settings.json.reference` and ~125 associated tests.
- `session-init.py` no longer computes active/stale counts or triggers compression — it increments `session_count` and logs a plain entry count.
- `auto-capture.py` no longer writes `scores` to `ref-cache.json` (dead data with no remaining consumer).

### Changed

- `README.md` statusline example model label `Sonnet 4.6 → Opus 4.7`; README/DEVELOPER updated to drop the removed subsystem.
- **`auto-capture` moved from the `Stop` hook to `SessionEnd`** — runs once at session teardown instead of after every response. Refactored into a reusable `capture(workdir)` that resolves the project dir from `CLAUDE_PROJECT_DIR` (fallback cwd) and `chdir`s before running git, fixing a non-project-CWD silent no-op; captures on all SessionEnd reasons (reason is logging-only, parsed best-effort so malformed/empty stdin never suppresses a capture).
- **Per-subagent model selection in the multi-agent skills** — `/code-review`, `/security-audit`, `/critical-review`, and `/implement-batch` now spawn each subagent with an explicit `model`: `opus` for the higher-stakes passes (architecture, correctness, injection/auth/crypto, implementers) and `sonnet` for the rest. Review/audit agents never default to `haiku`. `CLAUDE_CODE_SUBAGENT_MODEL` overrides these. Documented the mapping in DEVELOPER.md.
- **Shared review output-contract fragments** — extracted the boilerplate that is identical verbatim between the `/code-review` and `/security-audit` subagent prompts (scope/context opening, findings-list-format line, closing instruction) into `rules/review-output-contract.md`; each skill inlines the fragments at `<<shared:…>>` markers. Audit found the field list, severity scale, rationalizations, and red flags are intentionally domain-specific (not duplicated), so they stay per-skill; `/critical-review` reviews plans and does not consume the fragments. Added `tests/test_review_contract.py`.

### Fixed

- `tests/test_fileutil.py` — moved a module-level assignment below the deferred import to clear a long-standing ruff E402.

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
- **`install.sh`** — now fully supports upgrades in addition to fresh installs:
  - `install_settings()` function: `jq`-based merge of hooks and statusLine from `settings.json.reference` into `~/.claude/settings.json`. Backs up before modifying.
  - Already-installed symlinks detected and skipped without prompting (compares raw and resolved paths).
  - Stale symlink cleanup: broken symlinks pointing into the repo (from removed/renamed components) are detected and offered for removal.
  - Settings.json upgrade: repo-managed hook entries are stripped and re-added from the current reference on every run, handling renamed hooks, changed command formats, and removed hooks. User hooks are preserved.
  - Duplicate hook entries from older installer versions are deduplicated.
  - Repo-managed statusLine is updated to match the current reference; custom statusLine configurations are preserved.
  - CLAUDE.md, settings.json, and component prompts all skip when already current — a fully up-to-date install produces no prompts.
  - Extracted `merge_settings_json()` and `install_settings_needed()` helpers to eliminate logic duplication.
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

- **Shell test suites** — `tests/test_install.sh` and `tests/test_statusline.sh` covering installer, uninstaller, and status line
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

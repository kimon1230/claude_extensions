---
name: code-review
description: Run a parallel subagent code review of files, changes, or the entire project. Reviews architecture, code quality, correctness, performance, and maintainability from a senior engineer's perspective.
argument-hint: "[file/dir/changes]"
---

# Code Review

This skill must only be invoked from the main session, never from a subagent.

## 1. Determine Scope

a. If the user specified file paths, directories, or a description of what to review, use that as the scope.
b. If the user said "review my changes" or similar, use `git diff HEAD` (unstaged + staged) and `git diff --cached` as the scope. Include full file context for changed functions, not just the diff hunks. If no changes exist, tell the user and stop.
c. If no scope is specified, ask the user: "What should I review? Options: specific files/directories, recent changes (`git diff`), or the entire project."
d. For entire-project scope, identify all source files (exclude vendored/generated code, build artifacts, lock files, and test fixtures). Prioritize by architectural significance: import fan-in/fan-out, file size, and recent change frequency. Distribute files across agents by relevance to each agent's domain.
e. Confirm scope with the user before proceeding: "I'll code-review [scope description]. Correct?"

### Language & Project Detection

After determining scope, detect the primary language(s) and framework(s):
- Check file extensions, lock files (`package-lock.json`, `Pipfile.lock`, `Cargo.lock`), and config/module files (`tsconfig.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `go.sum`)
- Set `primary_language` and note the framework(s) in use
- Inform user: "Detected [language] project using [framework] — tailoring review accordingly."
- Check for project-level or user-level rule files (`rules/<language>.md`, e.g., `rules/python.md`) and instruct agents to read them if present for project-specific conventions.

Language detection shapes agent behavior — agents should apply language-idiomatic checks:
- **Python**: mutable default arguments, bare `except:`, missing type hints on public APIs, `os.path` vs `pathlib`
- **JavaScript/TypeScript**: `==` vs `===`, `var` usage, unhandled promise rejections, missing `async`/`await` error handling, prototype pollution patterns
- **Go**: unchecked errors, goroutine leaks, missing `defer` for cleanup, context propagation
- **Rust**: unnecessary `.clone()`, missing error propagation with `?`, overly broad lifetimes
- **Java**: checked exception abuse, mutable DTOs, missing `@Override`, raw types
- Other languages: apply general software engineering principles

## 2. Round 1 — Spawn Parallel Subagents

Spawn 5 subagents. Each agent reviews from a **senior distinguished engineer's perspective** — not looking for vulnerabilities (that's `/security-audit`), but evaluating whether this code is well-designed, maintainable, and correct.

- **Agent 1 — Architecture & Design** (module-level and above):
  - Separation of concerns — are responsibilities cleanly divided?
  - Coupling & cohesion — tightly coupled modules? Classes without a single clear purpose?
  - Abstraction levels — too many layers of indirection? Too few?
  - Design patterns — used appropriately, not cargo-culted?
  - Dependency direction — do dependencies flow correctly? Circular dependencies?
  - API surface — are public interfaces minimal? Could internal details leak?
  - Over-engineering — premature abstractions, unnecessary indirection, "enterprise astronaut" patterns, features nobody asked for
  - This agent does NOT review within-function quality (that's Agent 2) or runtime correctness (that's Agent 3).

- **Agent 2 — Code Quality & Readability** (within-function and expression-level):
  - Naming — do names convey intent? Consistent conventions? Abbreviations that obscure meaning?
  - Complexity — deep nesting (guideline: >3 levels warrants extraction), long functions (guideline: >40-60 lines depending on language), long parameter lists (>4 — consider a config/options object)
  - Duplication — copy-paste code that should be extracted (3+ instances, not premature extraction for 2)
  - Dead code — unused functions, unreachable branches, commented-out code
  - Clarity over cleverness — nested ternaries, dense one-liners, magic numbers, implicit behavior
  - Consistency — inconsistent patterns within the codebase (callbacks vs promises, mixed naming conventions)
  - Spaghetti indicators — deeply nested callbacks, unclear control flow, functions with multiple unrelated responsibilities
  - This agent does NOT review module-level architecture (that's Agent 1) or whether the code is correct (that's Agent 3).

- **Agent 3 — Correctness & Robustness** (does the code actually work?):
  - Logic errors — off-by-one, wrong operator, inverted conditions, short-circuit mistakes
  - Edge cases — empty collections, null/undefined, zero values, boundary values, Unicode, large inputs
  - Error handling — swallowed errors, missing error paths, overly broad catches, unhelpful error messages
  - Type safety — implicit conversions, loose equality, unvalidated type assumptions
  - Concurrency — race conditions, shared mutable state, missing synchronization, TOCTOU
  - Resource management — unclosed handles, missing cleanup, memory leaks
  - Invariant violations — assumptions not enforced, preconditions not checked at system boundaries
  - This agent does NOT review performance characteristics (that's Agent 4) or test quality (that's Agent 5).

- **Agent 4 — Performance & Efficiency** (is it fast enough and resource-conscious?):
  - Algorithmic complexity — O(n²) when O(n) is possible, unnecessary sorting, repeated lookups that should be indexed
  - Resource waste — unnecessary allocations, string concatenation in loops, loading entire datasets when streaming works
  - N+1 queries — database access in loops, missing joins, missing eager loading
  - Caching — missing obvious cache opportunities, stale caches without invalidation strategy
  - I/O patterns — synchronous I/O blocking event loops, unbuffered reads
  - Premature optimization — flag optimizations that hurt readability without measurable benefit
  - Bundle/payload size — importing entire libraries for one function
  - This agent does NOT review code correctness (that's Agent 3) or test coverage (that's Agent 5).

- **Agent 5 — Maintainability & Testing** (can this code be changed and trusted?):
  - Test coverage — are critical paths tested? Edge cases? Testing behavior, not implementation details?
  - Test quality — brittle tests tied to implementation, missing assertions, tests that always pass, flaky patterns
  - API contracts — are interfaces stable? Would changes break consumers?
  - Configuration — hardcoded values that should be configurable, environment-specific logic not properly abstracted
  - Documentation — missing context for non-obvious decisions (why, not what), misleading comments
  - Dependency health — too many deps for the functionality, abandoned/unmaintained libraries, major version lag. Note: CVE/vulnerability scanning is `/security-audit`'s job — this agent focuses on maintenance burden only.
  - Migration difficulty — if this code needs to change, how hard will it be?
  - This agent does NOT review code correctness (that's Agent 3) or performance (that's Agent 4).

**Each subagent's prompt MUST include these instructions verbatim:**
> Read the files in scope. For context, you may read up to 5 additional files (imports, configs, shared utilities) directly referenced by the scoped files. Do NOT scan the entire codebase.
>
> Review from a **senior distinguished engineer's perspective**. For each issue found, verify it is a genuine problem — not a reasonable trade-off for this codebase's context. Check if there is a project convention or framework constraint that justifies the pattern before flagging it.
>
> Return findings as a numbered list, max 10 items, highest severity first. Each item must have exactly these fields:
> - **Severity**: critical | major | minor
> - **Category**: short label (e.g., "Complexity", "Dead Code", "N+1 Query", "God Function", "Missing Tests")
> - **Location**: file path and line number or function name
> - **Issue**: one-sentence description of the problem and why it matters (e.g., "function handles both validation and persistence, making it impossible to test either in isolation" not just "function does too much")
> - **Suggestion**: concrete remediation — state what to do, not "consider" or "review" (e.g., "extract lines 45-80 into a `validate_input()` function" not "consider refactoring")
>
> Severity guide:
> - **critical**: Will cause bugs in production, data corruption, or makes the codebase unmaintainable. Must fix before shipping.
> - **major**: Significant design flaw, substantial tech debt, or correctness risk that will bite you later. Should fix.
> - **minor**: Style/convention issue, minor improvement, or defense-in-depth. Nice to fix but non-blocking.
>
> Return NO other text, except: if you encounter tool errors or cannot read required files, report that as your first finding with severity "critical" and category "tooling".

## 3. Synthesize Results

After all subagents complete, the main session:
- Deduplicates overlapping findings (same root cause reported by multiple agents)
- Merges related findings (e.g., multiple instances of the same pattern)
- Sorts by severity: critical > major > minor
- If a subagent returned zero findings, note that to the user (this is a good sign for that category)
- Present a consolidated report with:
  - **Summary**: total findings by severity, overall risk assessment. Note the detected language/framework from Section 1.
  - **Overall health**: "This codebase is [well-structured / has some debt / needs significant refactoring] because [1-2 sentence justification]" — anchor this assessment to finding counts (e.g., 0 critical + 0 major = well-structured; multiple major = has debt; any critical = needs refactoring).
  - **Findings**: the deduplicated list
  - **Positive observations**: well-implemented patterns worth noting (max 3 bullet points — keep it brief)

## 4. Remediation

If the user wants to fix issues:
- For **critical** and **major** findings: offer to fix them immediately, starting with critical
- Group related fixes into coherent batches (don't fix one naming issue at a time — batch all naming fixes together)
- For **minor** findings: list them as recommendations the user can address
- Apply fixes in the main session (not subagents), following existing code patterns
- Run tests after each batch of fixes
- After fixing, run a targeted follow-up review (Section 5)

## 5. Follow-Up Rounds

After applying fixes, automatically verify them:
- Spawn **2 parallel subagents** that review ONLY the changed code and its immediate context:
  - **Agent A — Architecture, Quality & Correctness** (combines agents 1-3 focus areas)
  - **Agent B — Performance, Maintainability & Testing** (combines agents 4-5 focus areas, plus checking that fixes didn't introduce new issues)
- Each subagent's prompt MUST include the full verbatim format template from Section 2, with only the first line replaced: "Review ONLY the following changed files/sections: [list]. Read at most 3 additional context files. Max 5 items. Also verify that the applied fixes are correct and complete — check for regressions." All other instructions (severity guide, field format, "Return NO other text") remain unchanged.
- Synthesize and present to user.
- **Stop condition**: a round produces **0 critical and 0 major** findings. Minor findings do not block — note them and declare the review complete.
- **Safety valve**: max 3 follow-up rounds (not counting the initial 5-agent round). If critical/major issues persist after 3 rounds, STOP — report what keeps recurring and flag that the recurring issues may require broader refactoring beyond the current review scope. Present remaining findings as a reference list.

## 6. Completion

When the stop condition is met, present a final summary:
- Findings resolved
- Remaining minor items (if any) as a reference list
- Do not begin further work unless the user explicitly requests it.

If the user does not approve fixes at any point, present the findings as a reference and end. Do not modify any files.

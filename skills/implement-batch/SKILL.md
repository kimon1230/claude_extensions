---
name: implement-batch
description: Implement a plan batch using parallel subagents. Each agent implements its module with tests, then the full suite is validated.
---

# Implement Batch

This skill must only be invoked from the main session, never from a subagent.

**Arguments**: `<plan-file> <batch-number>` (optional — will prompt if not provided)

1. **Identify the plan and batch:**
   a. If the user specified a plan file and batch number, use those.
   b. Else determine the project name: check `origin` git remote (parse last path component, strip `.git`) → git root basename → working directory basename.
   c. List files in `~/.claude/plans/<project-name>/`, sorted by modification time. If no plans found, tell the user and stop.
   d. If no batch number specified, read the plan and identify the next unimplemented batch. Confirm with the user: "I'll implement Batch N of `<plan-file>`. Correct?"

2. **Read the plan and extract the batch spec:**
   - Identify all modules/components in the target batch
   - Note dependencies between modules within the batch (some may need sequential implementation)
   - Note dependencies on prior batches (verify those are already implemented)
   - Read existing source files that the batch modifies or depends on

3. **Spawn parallel subagents for independent modules:**
   - Each subagent receives: the plan section for its module, relevant existing source files, and the project's testing conventions
   - **Each subagent's prompt MUST include these instructions verbatim:**
     > Implement the specified module per the plan. Also write comprehensive tests targeting 100% coverage of the new code.
     >
     > Follow existing project conventions for: file layout, naming, imports, docstrings, type hints.
     >
     > After writing code and tests, report back with:
     > - **Files created**: list with brief description
     > - **Files modified**: list with what changed
     > - **Test count**: number of tests written
     > - **Open questions**: anything ambiguous in the plan that you resolved with a judgment call
   - For modules that depend on other modules within the same batch, implement them sequentially after their dependencies complete.

4. **After all subagents complete, the main session:**
   - Reviews each agent's output for consistency (naming conflicts, import mismatches, duplicated code)
   - Resolves any conflicts between agents' work
   - Runs the full test suite: `pytest` (do not duplicate what hooks cover)
   - Runs lint/typecheck: `ruff check .` and `mypy` (if configured)
   - Reports: total tests pass/fail/skip, coverage percentage, any new failures

5. **If tests or quality checks fail:**
   - Diagnose and fix in the main session (not a subagent — keep context local)
   - Re-run checks after fixes
   - If a failure cannot be resolved within 3 attempts, stop and report to the user

6. **Summary to user:**
   - Batch N complete (or: Batch N blocked on [issue])
   - Files created/modified with paths
   - Test count and coverage
   - Key decisions or judgment calls made
   - Next batch ready to start (or: what blocks it)

---
name: compress
description: Manually compress session-progress entries, bypassing automatic threshold checks. Use when you want to force compression on demand.
---

# Compress Session Progress

1. **Determine the project name** (used for file paths):
   a. If a `~/.claude/status/*/session-progress.md` was written earlier this session, reuse that project name.
   b. Else if inside a git repo with a remote, use the `origin` remote. Parse the last path component, stripping any trailing `.git` (e.g., `my-lib` from `git@github.com:user/my-lib.git` or `https://github.com/user/my-lib.git`).
   c. Else use the basename of the git root (`git rev-parse --show-toplevel`).
   d. Else use the basename of the current working directory.
   e. If still ambiguous, ask the user.

2. **Run the compressor with force mode** using the Bash tool:

   ```bash
   .venv/bin/python -c "
   import sys, os
   sys.path.insert(0, os.path.expanduser('~/.claude/hooks'))
   from lib.compressor import compress
   print(compress(project_name='<PROJECT_NAME>', force=True))
   "
   ```

   Replace `<PROJECT_NAME>` with the value determined in step 1.

3. **Report the result** to the user:
   - If compression occurred, display the summary returned by the compressor (entries compressed, entries preserved, etc.).
   - If the compressor reports nothing was eligible, display: **"Nothing to compress — all N entries are active."** (where N is the entry count from the summary).
   - Do not treat "nothing to compress" as an error — it is a normal outcome.

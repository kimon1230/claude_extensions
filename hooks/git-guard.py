#!/usr/bin/env python3
"""PreToolUse hook: block ``git commit`` and ``git push`` Bash commands.

Checks Bash tool command tokens for a direct ``git commit`` / ``git push``
invocation and prints a JSON deny decision to stdout when one is found. This is a
cooperative guard (installed globally: the user handles all git commits and pushes
in every project), not an adversarial one.

Must NEVER crash — wraps everything in try/except and logs errors to stderr.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from git_guard_mod import main

if __name__ == "__main__":
    main()

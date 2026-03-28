#!/usr/bin/env python3
"""PreToolUse hook: block reads of files matching sensitive patterns.

Checks Read tool file paths and Bash tool command tokens against a set of
sensitive filename patterns (env files, SSH keys, credentials, etc.).
Prints a JSON block decision to stdout when a file should be blocked.

Must NEVER crash — wraps everything in try/except and logs errors to stderr.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sensitive_file_guard_mod import main

if __name__ == "__main__":
    main()

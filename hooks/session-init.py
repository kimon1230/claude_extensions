#!/usr/bin/env python3
"""SessionStart hook: increment session count and log context summary.

Runs on session startup/resume. Increments the session counter in
ref-cache.json and prints a brief context summary to stderr.

Must NEVER crash — silent on all errors.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from session_init_mod import main

if __name__ == "__main__":
    main()

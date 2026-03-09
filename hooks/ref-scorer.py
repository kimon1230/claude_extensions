#!/usr/bin/env python3
"""PostToolUse hook: score status entries against tool context.

Runs after Read, Edit, Write, Grep, Glob tools. Reads the hook payload from
stdin, extracts file paths and keywords, then scores each session-progress
entry and updates ref-cache.json.

Must NEVER produce output or raise — silent on all errors.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ref_scorer_mod import main

if __name__ == "__main__":
    main()

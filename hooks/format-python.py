#!/usr/bin/env python3
"""PostToolUse hook: auto-format Python files after Edit/Write (synchronous).

Finds ruff/black in the project's venv (bounded by the git repo root) and runs
ruff fix first (may add/remove imports), then black for final formatting.

Must NEVER crash — silent on all errors.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from format_python_mod import main

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Stop hook: run pytest when Claude finishes responding.

Only runs in a Python project with a test suite where files actually changed.
Exit 1 = non-blocking warning (Claude does NOT see it — no loop risk).
NEVER exit 2. Must never crash.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from run_tests_mod import main

if __name__ == "__main__":
    main()

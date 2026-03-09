#!/usr/bin/env python3
"""Stop hook: auto-capture uncommitted changes as session-progress entries.

Runs at session stop. Detects uncommitted git changes, classifies them,
and appends an ## Auto-captured section to session-progress.md.

Must NEVER produce output or raise — silent on all errors.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auto_capture_mod import main

if __name__ == "__main__":
    main()

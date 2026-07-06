#!/usr/bin/env python3
"""StatusLine hook: render user@host:cwd + model + context bar + cost.

Reads Claude Code's status-line JSON from stdin and prints a compact,
color-coded status line. Ports statusline-command.sh.

Must NEVER crash — silent on all errors.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from statusline_mod import main

if __name__ == "__main__":
    main()

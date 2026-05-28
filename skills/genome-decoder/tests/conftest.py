"""Pytest configuration for genome-decoder.

Puts ``scripts/`` on ``sys.path`` so the modules can be imported by their bare
names (``import _common``, ``import render``) exactly as they import each other
at runtime.
"""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

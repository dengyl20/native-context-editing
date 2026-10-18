"""Shared helpers for the NCE test suite. No third-party imports anywhere."""
from __future__ import annotations

import os
import sys

# Make ``nce`` importable no matter where the suite is started from, so
# ``python3 -m unittest discover -s tests`` works from the repository root
# and from a checkout mounted anywhere.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
TOY = os.path.join(ROOT, "examples", "data", "toy_trajectory.json")

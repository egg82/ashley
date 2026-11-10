"""Puts the contract suites' directory on the path, for the bare imports their modules make of each other."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "contract"))

"""The contract suite's `system` and `world` fixtures, loaded with its directory on the path (its modules import their
siblings by bare name)."""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "contract"))
_inflight = importlib.import_module("contract.test_inflight_resume")
system = _inflight.system
world = _inflight.world

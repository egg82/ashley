"""What `time_gate.py` excuses today. Both lists may only shrink: never add an entry to let a change through."""

HELD: frozenset[str] = frozenset()
HELD_SHARED: frozenset[str] = frozenset()

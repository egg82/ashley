"""Watch rows to records and checks to the JSON a `wakes` row carries."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from pydantic import TypeAdapter

from ..criteria import condition
from ..criteria.record import CHANGE_KINDS, Change, Fields
from .diff import Items, scalar
from .model import ArmedBy, State, Watch
from .watches import WatchesUnavailable

COLUMNS = ("id, household_id, person_id, kind, target, label, bench_id, armed_by, track, when_clauses, until_clauses, "
           "tools, interval_s, expires_at, state, reason, failures, version, series, baseline, next_check_at, "
           "armed_at, last_woke_at, ended_at, brief, standing_s IS NOT NULL, taint, made_conversation_id, made_turn_id")


def watch(r: tuple[Any, ...]) -> Watch:
    try:
        return Watch(int(r[0]), int(r[1]), int(r[2]), str(r[3]), str(r[4]), str(r[5]),
                     None if r[6] is None else int(r[6]), _armed_by(r[7]), tuple(str(t) for t in r[8]),
                     condition.from_json(r[9]), None if r[10] is None else condition.from_json(r[10]),
                     None if r[11] is None else tuple(str(t) for t in r[11]), float(r[12]), r[13], _state(r[14]),
                     None if r[15] is None else str(r[15]), int(r[16]), int(r[17]), int(r[18]),
                     None if r[19] is None else _items(r[19]), r[20], r[21], r[22], r[23],
                     None if r[24] is None else str(r[24]), bool(r[25]),
                     None if r[26] is None else str(r[26]), None if r[28] is None else (int(r[27]), int(r[28])))
    except ValueError as e:
        raise WatchesUnavailable("a stored watch could not be read") from e


def _armed_by(raw: Any) -> ArmedBy:
    return "handoff" if raw == "handoff" else "ashley"


def _state(raw: Any) -> State:
    if raw not in ("armed", "paused", "ended"):
        raise WatchesUnavailable("unknown state")
    return raw


def _items(raw: Any) -> Items:
    return {str(i): dict(fields) for i, fields in raw.items()}


def change_json(c: Change) -> dict[str, object]:
    return {"id": c.id, "kind": c.kind, "before": None if c.before is None else dict(c.before),
            "after": None if c.after is None else dict(c.after)}


def changed_wake(series: int, since: datetime, ended: bool, changes: tuple[Change, ...]) -> dict[str, object]:
    return {"what": "changed", "series": series, "since": since.isoformat(), "ended": "until" if ended else None,
            "items": [change_json(c) for c in changes]}


_OBJECT = TypeAdapter(dict[str, Any])
_LIST = TypeAdapter(list[Any])


def changes_of(wake: Mapping[str, object]) -> tuple[Change, ...]:
    """The changes a `changed` wake stores, as `changed_wake` wrote them. Raises ValueError for anything else."""
    return tuple(_change(i) for i in _LIST.validate_python(wake.get("items")))


def _change(raw: object) -> Change:
    body = _OBJECT.validate_python(raw)
    kind = body.get("kind")
    if kind not in CHANGE_KINDS:
        raise ValueError("a change is new, changed or gone")
    return Change(str(body.get("id")), kind, _fields(body.get("before")), _fields(body.get("after")))


def _fields(raw: object) -> Fields | None:
    return None if raw is None else {k: scalar(v, 1 << 30) for k, v in _OBJECT.validate_python(raw).items()}

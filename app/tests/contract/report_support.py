"""Helpers for the blind memory-report tests: log lines written by the app's own formatter (`ashley.logs.Logfmt`) at a
chosen time, the `respond.done` and `memory.apply` field sets as the app writes them, and a line finder for rendered
text."""

import logging
from datetime import UTC, datetime, timedelta

from ashley.logs import Logfmt
from ashley.memory.model import Fact, Kind, Visibility

T0 = datetime(2026, 10, 20, 9, 0, 0, tzinfo=UTC)
FORMATTER = Logfmt()


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def line(event: str, when: datetime = T0, **fields: object) -> str:
    """One line exactly as `ashley.logs` writes it, stamped `when`; a None field is dropped, as the app drops it."""
    record = logging.LogRecord("ashley.test", logging.INFO, "", 0, event, None, None)
    record.created = when.timestamp()
    record.msecs = when.microsecond // 1000
    record.fields = fields
    return FORMATTER.format(record)


def stamp(when: datetime) -> str:
    """The `ts` the formatter writes for `when`."""
    parsed = line("x", when).split(" ", 1)[0]
    assert parsed.startswith("ts=")
    return parsed[3:]


def _count(ids: str | None) -> object:
    return "unavailable" if ids == "unavailable" else len([i for i in (ids or "").split(",") if i])


def done(conversation: int, when: datetime = T0, *, standing: str | None = "", recalled: str | None = "",
         used: str = "", unrecalled: int = 0, kind: str = "chat", medium: str = "typed",
         speaker: str = "known") -> str:
    """A `respond.done` line; `standing`/`recalled` None leaves the id lists off, as a line from before them was."""
    tiers: dict[str, object] = {}
    if standing is not None:
        tiers["standing_facts"] = standing
    if recalled is not None:
        tiers["recalled_facts"] = recalled
    return line("respond.done", when, conversation=conversation, kind=kind, medium=medium, tool_rounds=0,
                tool_calls=0, speaker=speaker, recalled=_count(recalled), standing=_count(standing), **tiers,
                used_facts=used, used_unrecalled=unrecalled, duration_ms=12)


def applied(conversation: int, when: datetime = T0, *, inserted: str = "", add: int = 0, update: int = 0,
            invalidate: int = 0, forget: int = 0, noop: int = 0, deleted: int = 0,
            written_through: int | None = None, household: int = 1) -> str:
    return line("memory.apply", when, household=household, conversation=conversation, add=add, update=update,
                invalidate=invalidate, forget=forget, noop=noop, deleted=deleted, inserted=inserted,
                written_through=written_through)


def containing(out: str, token: str) -> list[str]:
    return [ln for ln in out.splitlines() if token in ln]


def the_line(out: str, token: str) -> str:
    """The one rendered line that carries `token` (a fact's text), so a marker is read on that fact's own line."""
    found = containing(out, token)
    assert len(found) == 1, f"{token!r} on {len(found)} lines of:\n{out}"
    return found[0]


def fact(fact_id: int, text: str, *, kind: Kind = "other", visibility: Visibility = "shared", conversation: int = 1,
         valid_to: datetime | None = None, superseded_by: int | None = None, standing: bool = False) -> Fact:
    return Fact(id=fact_id, household_id=5, about_id=None, owner_id=None, visibility=visibility, kind=kind,
                standing=standing, text=text, source_conversation_id=conversation, valid_from=T0, valid_to=valid_to,
                superseded_by=superseded_by)

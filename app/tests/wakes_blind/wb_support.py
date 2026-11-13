"""Shared pieces of the wake blind tests: a household with devices and tokens, wake builders, an in-memory Wakes that
keeps the interface's documented behaviour, and a log capture."""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import psycopg
from ashley.senses.wakes import Delivery, Due, Outcome, Received, Reminder, Route, SaidBefore, Scheduled, Wake, Wakes

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def wake(household_id: int, event_id: str = "ctx-1", event: str = "arrived", who: str | None = "person.alana",
         what: str | None = None, at: datetime = NOW) -> Wake:
    return Wake(household_id, event_id, event, who, what, at)


def add_device(url: str, household_id: int, token: str, name: str = "ha", house: bool = False) -> int:
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute("INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256, house) "
                           "VALUES (%s, %s, 'house', 'present', 'text', 'chat', %s, %s) RETURNING id",
                           (household_id, name, hashlib.sha256(token.encode()).digest(), house)).fetchone()
    assert row is not None
    return int(row[0])


def count(url: str, query: str, params: tuple[object, ...] = ()) -> int:
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute(query.encode(), params).fetchone()
    assert row is not None
    return int(row[0])


@dataclass
class MemoryWakes(Wakes):
    """Wakes that follow the interface's documentation, for the route tests: idempotent on (household, event id),
    `error` raised from every call when set."""

    stored: dict[tuple[int, str], tuple[int, Wake]] = field(default_factory=lambda: dict[tuple[int, str], tuple[int, Wake]]())
    settled: set[int] = field(default_factory=set[int])
    handed_in_by: list[int] = field(default_factory=list[int])
    error: Exception | None = None

    async def receive(self, device_id: int, wake: Wake) -> Received:
        if self.error is not None:
            raise self.error
        self.handed_in_by.append(device_id)
        key = (wake.household_id, wake.event_id)
        if key in self.stored:
            return Received(self.stored[key][0], False)
        self.stored[key] = (len(self.stored) + 1, wake)
        return Received(len(self.stored), True)

    async def due(self, limit: int) -> tuple[Due, ...]:
        return tuple(Due(i, w, 0.0) for i, w in self.stored.values() if i not in self.settled)[:limit]

    async def settle(self, wake_id: int, outcome: Outcome, next_due: datetime | None = None) -> bool:
        if wake_id in self.settled:
            return False
        self.settled.add(wake_id)
        return True

    async def routed(self, wake_id: int, person_id: int, route: Route, device_id: int) -> None:
        return None

    async def prune(self, older_than_s: float) -> int:
        return 0

    async def schedule(self, reminder: Reminder) -> int:
        raise AssertionError("the house's wakes never schedule a reminder")

    async def reminders(self, household_id: int, person_id: int) -> tuple[Scheduled, ...]:
        return ()

    async def cancel(self, household_id: int, person_id: int, wake_id: int) -> bool:
        return False

    async def edit(self, household_id: int, person_id: int, wake_id: int, changed: Reminder) -> bool:
        return False

    async def follow_up(self, household_id: int, wake_id: int, due_at: datetime, plan: str) -> int | None:
        return None

    async def refire(self, wake_id: int, after_s: float) -> int:
        return 0

    async def undelivered(self, limit: int, retry_s: float, within_s: float, *, at: Route = "phone", device_tries: int = 0,
                          device_retry_s: float = 0.0) -> tuple[Delivery, ...]:
        return ()

    async def claim(self, wake_id: int, retry_s: float, *, at: Route = "phone", device_tries: int = 0,
                    device_retry_s: float = 0.0) -> bool:
        return False

    async def delivered(self, wake_id: int, reached: bool) -> None:
        return None

    async def dismiss(self, household_id: int, person_id: int, wake_id: int) -> bool:
        return False

    async def said_before(self, wake_id: int, person_id: int) -> SaidBefore:
        return SaidBefore(None, None, None)


def ago(seconds: float) -> datetime:
    return NOW - timedelta(seconds=seconds)

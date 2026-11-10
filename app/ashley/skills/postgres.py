"""The Skills service in Postgres (`postgres_rows`). A change locks its household's kind for the transaction, so versions
are numbered one after the other on any pod of either site."""

import logging
from collections.abc import Generator, Mapping
from contextlib import contextmanager

import psycopg
from psycopg import errors

from .. import logs
from ..db.database import Database, DatabaseUnavailable
from ..text import has_nul
from . import postgres_rows as rows
from .config import SkillsConfig
from .seeds import Seed
from .skills import Edited, Kind, Skill, SkillRefused, Skills, SkillsUnavailable, Status, Version

log = logging.getLogger("ashley.skills")
READ_ONLY_TRANSACTION = "25006"


@contextmanager
def _translated() -> Generator[None]:
    try:
        yield
    except DatabaseUnavailable as e:
        raise SkillsUnavailable("no database connection") from e
    except psycopg.OperationalError as e:
        raise SkillsUnavailable("database unreachable") from e
    except errors.ForeignKeyViolation as e:
        raise SkillRefused("unknown_kind") from e
    except psycopg.Error as e:
        if e.sqlstate == READ_ONLY_TRANSACTION:
            raise SkillsUnavailable("database is not writable") from e
        raise


def _fits(text: str, limit: int) -> bool:
    return bool(text.strip()) and len(text) <= limit and not has_nul(text)


class PostgresSkills(Skills):
    def __init__(self, database: Database, config: SkillsConfig, seeds: Mapping[str, Seed]) -> None:
        self._database = database
        self._config = config
        self._seeds = seeds

    async def _require(self, conn: rows.Conn, household_id: int, kind: str) -> None:
        """Raises SkillRefused (`unknown_kind`) unless `kind` is a seed's or one of the household's."""
        if kind not in self._seeds and kind not in await rows.kinds(conn, household_id):
            raise SkillRefused("unknown_kind")

    def _notes(self, *notes: str) -> None:
        if not all(_fits(n, self._config.max_note_chars) for n in notes):
            raise SkillRefused("bad_note")

    async def kinds(self, household_id: int) -> tuple[Kind, ...]:
        with _translated():
            async with self._database.connection() as conn:
                own = await rows.kinds(conn, household_id)
        found = {k: s.label for k, s in self._seeds.items()} | own
        return tuple(Kind(k, label) for k, label in sorted(found.items()))

    async def add_kind(self, household_id: int, kind: str, label: str) -> Kind:
        if not self._config.slug_ok(kind) or not self._config.label_ok(label):
            raise SkillRefused("bad_kind")
        with _translated():
            async with self._database.connection() as conn:
                started = await rows.insert_kind(conn, household_id, kind, label.strip())
                own = await rows.kinds(conn, household_id)
        if started:
            logs.info(log, "skills.kind_added", household=household_id, kind=kind)
        return Kind(kind, own[kind])

    async def current(self, household_id: int, kind: str) -> Skill | None:
        with _translated():
            async with self._database.connection() as conn:
                await self._require(conn, household_id, kind)
                found = await rows.head(conn, household_id, kind)
                seed = self._seeds.get(kind)
                edits = await rows.live_count(conn, household_id, kind)
                pinned = await rows.is_pinned(conn, household_id, kind)
                waiting = await rows.proposal(conn, household_id, kind)
        if found is None and seed is None:
            return None if waiting is None else Skill(kind, 0, "", 0, pinned, None, None, waiting)
        if found is None:
            assert seed is not None
            return Skill(kind, 0, seed.body, 0, pinned, seed.seeded_from, None, waiting)
        return Skill(kind, found[0], found[1], edits, pinned, None, found[2], waiting)

    async def edit(self, household_id: int, kind: str, body: str, what: str, why: str, base_version: int,
                   bench_id: int | None, person_id: int | None) -> Edited:
        if not _fits(body, self._config.max_body_chars):
            raise SkillRefused("bad_body")
        self._notes(what, why)
        return await self._write(household_id, kind, body, what, why, base_version, None, bench_id, person_id)

    async def rollback(self, household_id: int, kind: str, to_version: int, why: str, bench_id: int | None,
                       person_id: int | None) -> Edited:
        self._notes(why)
        what = "Rolled back to the seed" if to_version == 0 else f"Rolled back to version {to_version}"
        with _translated():
            async with self._database.connection() as conn:
                await rows.lock(conn, household_id, kind)
                await self._require(conn, household_id, kind)
                target = await self._body_of(conn, household_id, kind, to_version)
                if target is None:
                    raise SkillRefused("no_such_version")
                found = await rows.head(conn, household_id, kind)
                done = await self._insert(conn, household_id, kind, target, what, why, found[0] if found else 0,
                                          to_version, bench_id, person_id)
        return self._logged(household_id, kind, done, bench_id, person_id, len(target))

    async def _body_of(self, conn: rows.Conn, household_id: int, kind: str, version: int) -> str | None:
        if version == 0:
            seed = self._seeds.get(kind)
            return None if seed is None else seed.body
        return await rows.live_body(conn, household_id, kind, version)

    async def _write(self, household_id: int, kind: str, body: str, what: str, why: str, base_version: int,
                     restored_from: int | None, bench_id: int | None, person_id: int | None) -> Edited:
        with _translated():
            async with self._database.connection() as conn:
                await rows.lock(conn, household_id, kind)
                await self._require(conn, household_id, kind)
                found = await rows.head(conn, household_id, kind)
                if base_version != (found[0] if found else 0):
                    raise SkillRefused("stale")
                done = await self._insert(conn, household_id, kind, body, what, why, base_version, restored_from,
                                          bench_id, person_id)
        return self._logged(household_id, kind, done, bench_id, person_id, len(body))

    async def _insert(self, conn: rows.Conn, household_id: int, kind: str, body: str, what: str, why: str,
                      base_version: int, restored_from: int | None, bench_id: int | None,
                      person_id: int | None) -> Edited:
        """The next version of `kind`, once `body` differs from the live text, live or waiting by the pin."""
        found = await rows.head(conn, household_id, kind)
        seed = self._seeds.get(kind)
        if body == (found[1] if found else seed.body if seed else None):
            raise SkillRefused("unchanged")
        status: Status = "proposed" if person_id is None and await rows.is_pinned(conn, household_id, kind) else "live"
        version = await rows.next_version(conn, household_id, kind)
        await rows.insert(conn, household_id, kind, version, body, what, why, status, base_version, restored_from,
                          bench_id, person_id)
        return Edited(version, status)

    def _logged(self, household_id: int, kind: str, done: Edited, bench_id: int | None, person_id: int | None,
                chars: int) -> Edited:
        logs.info(log, "skills.edited", household=household_id, kind=kind, version=done.version, status=done.status,
                  by="ashley" if person_id is None else "person", bench=bench_id, chars=chars)
        return done

    async def changelog(self, household_id: int, kind: str) -> tuple[Version, ...]:
        with _translated():
            async with self._database.connection() as conn:
                await self._require(conn, household_id, kind)
                return await rows.changelog(conn, household_id, kind, self._config.changelog_read)

    async def pin(self, household_id: int, kind: str, pinned: bool) -> None:
        with _translated():
            async with self._database.connection() as conn:
                await self._require(conn, household_id, kind)
                await rows.set_pinned(conn, household_id, kind, pinned)
        logs.info(log, "skills.pinned", household=household_id, kind=kind, pinned=pinned)

    async def decide(self, household_id: int, kind: str, version: int, approve: bool) -> Edited:
        with _translated():
            async with self._database.connection() as conn:
                await rows.lock(conn, household_id, kind)
                await self._require(conn, household_id, kind)
                proposed = await rows.waiting(conn, household_id, kind, version)
                if proposed is None:
                    raise SkillRefused("not_proposed")
                found = await rows.head(conn, household_id, kind)
                if approve and proposed.base_version != (found[0] if found else 0):
                    raise SkillRefused("stale")
                status: Status = "live" if approve else "declined"
                await rows.set_status(conn, household_id, kind, version, status)
        logs.info(log, "skills.decided", household=household_id, kind=kind, version=version, status=status)
        return Edited(version, status)

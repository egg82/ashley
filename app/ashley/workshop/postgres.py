"""The Workshop in Postgres: tables `benches`, `bench_pieces` (the pieces as they stand) and `bench_commands` (the log).
A command locks its bench's row, so commands on one bench are decided one at a time, on any pod of either site."""

import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from typing import get_args

import psycopg
from psycopg import errors

from .. import logs, services
from ..db.database import Database, DatabaseUnavailable
from ..live.events import BenchChanged, BenchCued, Event, ScreenChanged, Shown
from ..live.live import Live
from ..text import has_nul
from . import postgres_frames as frames
from . import postgres_reactions as reactions
from . import postgres_rows as rows
from .commands import (Add, Added, Archived, Command, Cued, Edit, Install, Propose, Removed, Rename, Renamed, Restored, Run,
                       ScreenCommand, piece_of, type_of)
from .decide import Accepted, Decision
from .model import Bench, By, Owner
from .postgres_apply import decided
from .postgres_turn import undo_all
from .postgres_screen import PostgresScreens
from .proposals import pending
from . import screen_seed
from .rules import Rules, load_screen
from .reactions import Unseen
from .undo_walk import next_undo
from .workshop import (Applied, BenchClosed, BenchNotFound, BenchView, Logged, Placed, ScreenView, SiteFrame,
                       TurnUndone, UnknownOwner, Workshop, WorkshopUnavailable)

log = logging.getLogger("ashley.workshop")
READ_ONLY_TRANSACTION = "25006"
_SCREEN_COMMANDS: tuple[type, ...] = get_args(ScreenCommand)


@contextmanager
def _translated() -> Generator[None]:
    try:
        yield
    except DatabaseUnavailable as e:
        raise WorkshopUnavailable("no database connection") from e
    except psycopg.OperationalError as e:
        raise WorkshopUnavailable("database unreachable") from e
    except errors.ForeignKeyViolation as e:
        if e.diag.constraint_name == "benches_owner_id_household_id_fkey":
            raise UnknownOwner("not a person of that household") from e
        raise
    except psycopg.Error as e:
        if e.sqlstate == READ_ONLY_TRANSACTION:
            raise WorkshopUnavailable("database is not writable") from e
        raise


def _text_of(command: Command) -> str:
    """The strings of `command` joined, for the NUL check."""
    if isinstance(command, Add):
        return f"{command.kind}{command.text.title}{command.text.body}"
    if isinstance(command, Run):
        return command.language
    if isinstance(command, Propose):
        return command.turn_off or ""
    if isinstance(command, Install):
        return command.automation_id
    if isinstance(command, Rename):
        return command.title
    return f"{command.text.title}{command.text.body}" if isinstance(command, Edit) else ""


class _GroupRefused(Exception):
    """A turn's undo had a refusal: raised inside the transaction so none of it is kept."""

    def __init__(self, result: TurnUndone) -> None:
        self.result = result


def _announced(owner: Owner, bench_id: int, decision: Accepted, command: Command) -> Event:
    """A cue is told to the open screens as it is (`BenchCued`) and is no change of the bench; any other accepted
    command is a `BenchChanged`."""
    shown, effect = Shown(owner.household_id, owner.person_id), decision.effect
    if isinstance(effect, Cued):
        return BenchCued(shown, bench_id, effect.piece_id, effect.action, effect.seconds)
    return BenchChanged(shown, bench_id, decision.seq, "her" if command.by.person_id is None else "person")


class PostgresWorkshop(Workshop):
    def __init__(self, database: Database, rules: Rules, screen_rules: Rules | None = None) -> None:
        self._database = database
        self._rules = rules
        self._screen_rules = load_screen() if screen_rules is None else screen_rules
        self._screens = PostgresScreens(database, self._screen_rules, screen_seed.load(self._screen_rules))

    async def open(self, owner: Owner, title: str) -> Bench:
        if not title.strip() or len(title) > self._rules.title_max_chars or has_nul(title):
            raise ValueError("a bench's title is 1 to title_max_chars characters, not only whitespace, with no NUL")
        with _translated():
            async with self._database.connection() as conn:
                bench = await rows.insert_bench(conn, owner, title)
        logs.info(log, "workshop.opened", bench=bench.id, person=owner.person_id)
        return bench

    async def of_kind(self, household_id: int, kind: str) -> tuple[Placed, ...]:
        with _translated():
            async with self._database.connection() as conn:
                return await rows.of_kind(conn, household_id, kind)

    async def open_benches(self, owner: Owner) -> list[Bench]:
        with _translated():
            async with self._database.connection() as conn:
                return await rows.open_benches(conn, owner)

    async def closed_benches(self, owner: Owner) -> list[Bench]:
        with _translated():
            async with self._database.connection() as conn:
                return await rows.closed_benches(conn, owner)

    async def close(self, owner: Owner, bench_id: int) -> Bench:
        return await self._set_closed(owner, bench_id, True)

    async def reopen(self, owner: Owner, bench_id: int) -> Bench:
        return await self._set_closed(owner, bench_id, False)

    async def _set_closed(self, owner: Owner, bench_id: int, closing: bool) -> Bench:
        with _translated():
            async with self._database.connection() as conn:
                found = await rows.bench(conn, owner, bench_id, lock=True)
                if found is None:
                    raise BenchNotFound(str(bench_id))
                changed = await (rows.close_bench if closing else rows.reopen_bench)(conn, bench_id)
        if changed is None:
            return found[0]
        logs.info(log, "workshop.closed" if closing else "workshop.reopened", bench=bench_id)
        return changed

    async def set_work(self, owner: Owner, bench_id: int, work: str | None) -> Bench:
        if work is not None and (not work.strip() or has_nul(work)):
            raise ValueError("a bench's kind of work is not blank")
        with _translated():
            async with self._database.connection() as conn:
                found = await rows.bench(conn, owner, bench_id, lock=True)
                if found is None:
                    raise BenchNotFound(str(bench_id))
                bench, next_seq = found
                if bench.work == work:
                    return bench
                await rows.write_work(conn, bench_id, work)
        logs.info(log, "workshop.work", bench=bench_id, kind=work)
        services.get(Live).publish(BenchChanged(Shown(owner.household_id, owner.person_id), bench_id, next_seq - 1))
        return replace(bench, work=work)

    async def read(self, owner: Owner, bench_id: int) -> BenchView:
        with _translated():
            async with self._database.connection() as conn:
                found = await rows.bench(conn, owner, bench_id)
                if found is None:
                    raise BenchNotFound(str(bench_id))
                pieces = await rows.pieces(conn, bench_id)
                shelf = await rows.shelf(conn, bench_id)
                recent = await rows.logged(conn, bench_id, self._rules.recent_commands)
                changed = await rows.changes(conn, bench_id)
                undo_next = next_undo(await rows.steps(conn, bench_id, self._rules.undo_window))
                proposals = pending(pieces, await rows.install_effects(conn, bench_id))
                pointers = await rows.pointers(conn, bench_id)
                measured = await frames.site_frames(conn, bench_id)
                shown = await rows.surfaced(conn, bench_id)
        return BenchView(found[0], pieces, tuple(recent), changed, undo_next, shelf, proposals, pointers, measured, shown)

    async def record_site_frame(self, household_id: int, bench_id: int, url: str, frame: SiteFrame) -> None:
        if has_nul(url) or has_nul(frame.title):
            raise ValueError("a site's address and title hold no NUL")
        with _translated():
            async with self._database.connection() as conn:
                await frames.record(conn, household_id, bench_id, url, frame)

    async def log(self, owner: Owner, bench_id: int) -> list[Logged]:
        with _translated():
            async with self._database.connection() as conn:
                if await rows.bench(conn, owner, bench_id) is None:
                    raise BenchNotFound(str(bench_id))
                return await rows.logged(conn, bench_id)

    async def unseen(self, pause_s: float, limit: int, listed: int) -> tuple[Unseen, ...]:
        with _translated():
            async with self._database.connection() as conn:
                return await reactions.unseen(conn, pause_s, limit, listed)

    async def reaction_ages(self, bench_id: int, window_s: float) -> tuple[float, ...]:
        with _translated():
            async with self._database.connection() as conn:
                return await reactions.reaction_ages(conn, bench_id, window_s)

    async def reacted(self, household_id: int, bench_id: int, to_seq: int, keep_s: float) -> None:
        with _translated():
            async with self._database.connection() as conn:
                await reactions.record(conn, household_id, bench_id, to_seq, keep_s)

    async def apply(self, owner: Owner, bench_id: int, command: Command) -> Applied:
        if command.by.person_id not in (None, owner.person_id):
            raise ValueError("a person's command is made on their own bench")
        if has_nul(_text_of(command)):
            raise ValueError("a command's text holds no NUL")
        started = time.monotonic()
        with _translated():
            async with self._database.connection() as conn:
                found = await rows.bench(conn, owner, bench_id, lock=True)
                if found is None:
                    raise BenchNotFound(str(bench_id))
                bench, next_seq = found
                if bench.closed_at is not None:
                    raise BenchClosed(str(bench_id))
                decision = await decided(conn, bench_id, bench.household_id, next_seq, bench.title, command, self._rules)
        applied = self._applied(decision)
        self._logged(bench_id, command, decision, applied, started)
        if isinstance(decision, Accepted):
            services.get(Live).publish(_announced(owner, bench_id, decision, command))
        return applied

    async def undo_turn(self, owner: Owner, bench_id: int, by: By, seq: int) -> TurnUndone:
        if by.person_id not in (None, owner.person_id):
            raise ValueError("a person's command is made on their own bench")
        try:
            with _translated():
                async with self._database.connection() as conn:
                    found = await rows.bench(conn, owner, bench_id, lock=True)
                    if found is None:
                        raise BenchNotFound(str(bench_id))
                    bench, next_seq = found
                    if bench.closed_at is not None:
                        raise BenchClosed(str(bench_id))
                    done, last = await undo_all(conn, bench_id, bench.household_id, next_seq, bench.title, self._rules,
                                                by, seq)
                    if done.refused:
                        raise _GroupRefused(done)
        except _GroupRefused as e:
            logs.info(log, "workshop.undo_turn", bench=bench_id, undone=0, refused=len(e.result.refused))
            return e.result
        logs.info(log, "workshop.undo_turn", bench=bench_id, undone=len(done.undone), refused=0)
        if last is not None:
            services.get(Live).publish(BenchChanged(Shown(owner.household_id, owner.person_id), bench_id, last,
                                                    "her" if by.person_id is None else "person"))
        return done

    async def screen(self, household_id: int, device_id: int) -> ScreenView:
        with _translated():
            return await self._screens.view(household_id, device_id)

    async def apply_screen(self, household_id: int, device_id: int, command: ScreenCommand) -> Applied:
        if not isinstance(command, _SCREEN_COMMANDS):
            raise ValueError("a screen takes Add, Remove, Move, Edit and Undo")
        if has_nul(_text_of(command)):
            raise ValueError("a command's text holds no NUL")
        started = time.monotonic()
        with _translated():
            done = await self._screens.apply(household_id, device_id, command)
        applied = self._applied(done.decision)
        if done.seeded:
            logs.info(log, "workshop.screen_opened", bench=done.bench_id, device=device_id, seeded=done.seeded)
        self._logged(done.bench_id, command, done.decision, applied, started, self._screen_rules, device=device_id)
        if done.seeded or isinstance(done.decision, Accepted):
            services.get(Live).publish(ScreenChanged(Shown(household_id, None), device_id, done.decision.seq))
        return applied

    def _applied(self, decision: Decision) -> Applied:
        if isinstance(decision, Accepted):
            return Applied(decision.seq, "accepted", piece_of(decision.effect), decision.effect)
        return Applied(decision.seq, decision.reason, None)

    def _logged(self, bench_id: int, command: Command, decision: Decision, applied: Applied, started: float,
                rules: Rules | None = None, **more: int) -> None:
        rules = self._rules if rules is None else rules
        kind = None
        if isinstance(decision, Accepted):
            effect = decision.effect
            if isinstance(effect, Renamed):
                whole = None
            else:
                whole = (effect.piece if isinstance(effect, (Added, Removed, Archived, Restored))
                         else decision.state.piece(effect.piece_id))
            kind = None if whole is None else whole.kind
        elif isinstance(command, Add) and command.kind in rules.kinds:
            kind = command.kind
        logs.info(log, "workshop.command", bench=bench_id, seq=applied.seq, type=type_of(command),
                  piece=applied.piece_id, kind=kind, by=command.by.author, outcome=applied.outcome, **more,
                  ms=round((time.monotonic() - started) * 1000))

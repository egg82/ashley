"""A device's screen in Postgres: reading it, and deciding a command on it, creating its bench on the first one. The
bench is the Workshop's own (`postgres_rows`, `postgres_apply`), found by `device_id` instead of by owner."""

from dataclasses import dataclass

from ..db.database import Database
from . import postgres_rows as rows
from . import postgres_screens as screens
from . import screen_seed
from .commands import ScreenCommand
from .decide import Accepted, BenchState, Decision, decide
from .model import HER, Author, Size
from .postgres_apply import decided
from .rules import Rules
from .undo_walk import next_undo
from .workshop import ScreenNotFound, ScreenView


@dataclass(frozen=True)
class Done:
    """What `PostgresScreens.apply` decided: on bench `bench_id`, `decision`, after `seeded` Adds laid the screen out
    (0 when the bench existed)."""

    bench_id: int
    decision: Decision
    seeded: int


class PostgresScreens:
    def __init__(self, database: Database, rules: Rules, seed: tuple[tuple[str, Size], ...]) -> None:
        self._database = database
        self._rules = rules
        self._seed = seed

    async def view(self, household_id: int, device_id: int) -> ScreenView:
        """The device's screen, the seed when it has no bench. Raises ScreenNotFound."""
        async with self._database.connection() as conn:
            if not await screens.device_is_live(conn, household_id, device_id):
                raise ScreenNotFound(str(device_id))
            found = await screens.bench(conn, household_id, device_id)
            if found is None:
                controls = await screens.device_controls(conn, household_id, device_id)
                seeded = screen_seed.state_of(self._seed, self._rules, controls).pieces
                return ScreenView(device_id, False, 0, seeded, None, {p.id: HER.author for p in seeded})
            bench_id, next_seq, _ = found
            steps = await rows.steps(conn, bench_id, self._rules.undo_window)
            undo_next = next_undo([step for step in steps if step.seq > len(self._seed)])
            authors: dict[int, Author] = {piece: change.by.author
                                          for piece, change in (await rows.changes(conn, bench_id)).items()}
            return ScreenView(device_id, True, next_seq - 1, await rows.pieces(conn, bench_id), undo_next, authors)

    async def apply(self, household_id: int, device_id: int, command: ScreenCommand) -> Done:
        """`command` decided on the device's screen, which is first laid out when it has no bench. Raises
        ScreenNotFound, and ValueError for a `by` that is no person of the household."""
        async with self._database.connection() as conn:
            if not await screens.device_is_live(conn, household_id, device_id, lock=True):
                raise ScreenNotFound(str(device_id))
            person = command.by.person_id
            if person is not None and not await screens.person_is_of(conn, household_id, person):
                raise ValueError("a person's command is made by a person of the household")
            found = await screens.bench(conn, household_id, device_id, lock=True)
            seeded = 0
            if found is None:
                inserted = await screens.insert_bench(conn, household_id, device_id)
                assert inserted is not None, "the device row is locked, so no other transaction inserted its bench"
                seeded = await self._lay_out(conn, household_id, device_id, inserted)
                found = (inserted, seeded + 1, screen_seed.TITLE)
            bench_id, next_seq, title = found
            return Done(bench_id, await decided(conn, bench_id, household_id, next_seq, title, command, self._rules), seeded)

    async def _lay_out(self, conn: screens.Conn, household_id: int, device_id: int, bench_id: int) -> int:
        """The seed's Adds logged and stored on the new bench, the device's rows moved into its controls piece; how many
        Adds."""
        controls = await screens.device_controls(conn, household_id, device_id)
        state = BenchState(title=screen_seed.TITLE)
        adds = screen_seed.commands(self._seed, self._rules, controls)
        for add in adds:
            state = await _added(conn, bench_id, household_id, state, add, self._rules)
        await rows.write_pieces(conn, bench_id, household_id, ((), ()), (state.pieces, state.shelf))
        await screens.delete_device_controls(conn, device_id)
        return len(adds)


async def _added(conn: screens.Conn, bench_id: int, household_id: int, state: BenchState, add: ScreenCommand,
                 rules: Rules) -> BenchState:
    decision = decide(state, add, rules)
    assert isinstance(decision, Accepted), "the seed replays accepted (screen_seed.load checked it)"
    await rows.record(conn, bench_id, household_id, add, decision)
    return decision.state

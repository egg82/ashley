"""Undoing a turn's commands together, in the caller's transaction on a bench whose row it holds locked."""

from typing import Any

from psycopg import AsyncConnection

from .commands import Reason, Undo
from .decide import Accepted
from .model import By
from .postgres_apply import decided
from .rules import Rules
from .workshop import TurnUndone

Conn = AsyncConnection[tuple[Any, ...]]

NOT_UNDONE = ("undo", "run", "propose", "install", "cue", "point", "surfaced")


async def turn_seqs(conn: Conn, bench_id: int, seq: int) -> list[int]:
    """The `seq`s, newest first, of the accepted commands made in the turn that made command `seq`, leaving out those
    no Undo names (`NOT_UNDONE`) and those an accepted Undo already took back. Empty when `seq` was made in no turn."""
    cur = await conn.execute(
        "SELECT c.seq FROM bench_commands c WHERE c.bench_id = %s AND c.outcome = 'accepted' "
        "AND c.command->'turn' = (SELECT command->'turn' FROM bench_commands WHERE bench_id = %s AND seq = %s) "
        "AND NOT c.command->>'type' = ANY(%s) AND NOT EXISTS (SELECT 1 FROM bench_commands u "
        "WHERE u.bench_id = c.bench_id AND u.outcome = 'accepted' AND u.command->>'type' = 'undo' "
        "AND u.seq > c.seq AND (u.command->>'seq')::int = c.seq) ORDER BY c.seq DESC",
        (bench_id, bench_id, seq, list(NOT_UNDONE)))
    return [int(r[0]) for r in await cur.fetchall()]


async def undo_all(conn: Conn, bench_id: int, household_id: int, next_seq: int, title: str, rules: Rules, by: By,
                   seq: int) -> tuple[TurnUndone, int | None]:
    """Each command of the turn undone in turn, the writes made as for any Undo. The caller rolls them back when the
    result has refusals. The `seq` of the last Undo logged goes with it, None when none was."""
    group = await turn_seqs(conn, bench_id, seq)
    if not group:
        return TurnUndone((), ((seq, "nothing_to_undo"),)), None
    undone: list[int] = []
    refused: list[tuple[int, Reason]] = []
    last = None
    for target in group:
        decision = await decided(conn, bench_id, household_id, next_seq, title, Undo(by, target), rules)
        next_seq, title, last = decision.state.next_seq, decision.state.title, decision.seq
        if isinstance(decision, Accepted):
            undone.append(target)
        else:
            refused.append((target, decision.reason))
    return TurnUndone(() if refused else tuple(undone), tuple(refused)), last

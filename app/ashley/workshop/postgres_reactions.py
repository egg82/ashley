"""The SQL of a bench's reactions (`ashley.workshop.reactions`), one statement per function, each on a connection the
caller holds."""

from typing import Any

from psycopg import AsyncConnection

from .reactions import Done, Unseen

Conn = AsyncConnection[tuple[Any, ...]]
_PERSON = "c.person_id IS NOT NULL AND c.outcome = 'accepted' AND c.command->>'type' NOT IN ('cue', 'point', 'surfaced')"
_PIECE = "COALESCE(c.effect->>'piece_id', c.effect->'piece'->>'id')::integer"


async def unseen(conn: Conn, pause_s: float, limit: int, listed: int) -> tuple[Unseen, ...]:
    """The open benches with a person's accepted commands after their last record, the newest quiet for `pause_s`."""
    cur = await conn.execute(
        "WITH seen AS (SELECT b.id, b.household_id, b.owner_id, coalesce((SELECT max(r.to_seq) FROM bench_reactions r "
        "WHERE r.bench_id = b.id), 0) AS after FROM benches b WHERE b.closed_at IS NULL AND b.owner_id IS NOT NULL) "
        "SELECT s.id, s.household_id, s.owner_id, s.after, max(c.seq), count(*), max(c.at) AS last_at FROM seen s "
        f"JOIN bench_commands c ON c.bench_id = s.id AND c.seq > s.after AND {_PERSON} "
        "GROUP BY s.id, s.household_id, s.owner_id, s.after "
        "HAVING max(c.at) <= now() - make_interval(secs => %s) ORDER BY last_at, s.id LIMIT %s", (pause_s, limit))
    found = await cur.fetchall()
    return tuple([Unseen(int(r[0]), int(r[1]), int(r[2]), int(r[3]), int(r[4]), int(r[5]),
                         await _done(conn, int(r[0]), int(r[3]), int(r[4]), listed)) for r in found])


async def _done(conn: Conn, bench_id: int, after: int, to_seq: int, listed: int) -> tuple[Done, ...]:
    cur = await conn.execute(
        f"SELECT c.seq, c.command->>'type', {_PIECE}, p.kind, c.at FROM bench_commands c "
        f"LEFT JOIN bench_pieces p ON p.bench_id = c.bench_id AND p.piece_id = {_PIECE} "
        f"WHERE c.bench_id = %s AND c.seq > %s AND c.seq <= %s AND {_PERSON} ORDER BY c.seq DESC LIMIT %s",
        (bench_id, after, to_seq, listed))
    return tuple(Done(int(r[0]), str(r[1]), None if r[2] is None else int(r[2]), r[3], r[4])
                 for r in reversed(await cur.fetchall()))


async def reaction_ages(conn: Conn, bench_id: int, window_s: float) -> tuple[float, ...]:
    cur = await conn.execute(
        "SELECT extract(epoch FROM now() - at) FROM bench_reactions WHERE bench_id = %s "
        "AND at > now() - make_interval(secs => %s) ORDER BY at DESC", (bench_id, window_s))
    return tuple(float(r[0]) for r in await cur.fetchall())


async def record(conn: Conn, household_id: int, bench_id: int, to_seq: int, keep_s: float) -> None:
    """The record, once per `to_seq`, and the bench's older ones past `keep_s` deleted, its newest always kept."""
    await conn.execute("INSERT INTO bench_reactions (bench_id, household_id, to_seq) VALUES (%s, %s, %s) "
                       "ON CONFLICT (bench_id, to_seq) DO NOTHING", (bench_id, household_id, to_seq))
    await conn.execute(
        "DELETE FROM bench_reactions WHERE bench_id = %s AND at < now() - make_interval(secs => %s) "
        "AND to_seq < (SELECT max(to_seq) FROM bench_reactions WHERE bench_id = %s)", (bench_id, keep_s, bench_id))

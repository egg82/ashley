"""The rows a bench replay reads, the same way from production at capture and from its scratch database after a
replay: a bench's command log, the turns on its thread and her looks on it."""

from typing import Any

from psycopg import AsyncConnection

from .bench_replay_snapshot import Command, Look, Said, object_of


async def commands(conn: AsyncConnection[Any], bench_id: int) -> tuple[Command, ...]:
    rows = await (await conn.execute(
        "SELECT seq, extract(epoch FROM at)::float8, person_id IS NOT NULL, command, outcome, effect "
        "FROM bench_commands WHERE bench_id = %s ORDER BY seq", (bench_id,))).fetchall()
    return tuple(Command(seq, at, person, outside(effect), command, outcome, effect)
                 for seq, at, person, command, outcome, effect in rows)


def outside(effect: dict[str, Any] | None) -> bool:
    """The flag her change was made under, as its effect records it."""
    piece = object_of((effect or {}).get("piece")) or {}
    return bool((effect or {}).get("outside")) or bool(piece.get("outside"))


async def turns(conn: AsyncConnection[Any], household_id: int, bench_id: int, first: int, last: int) -> tuple[Said, ...]:
    """The turns on the bench's thread in conversations `first` to `last`, by id."""
    rows = await (await conn.execute(
        "SELECT t.id, t.conversation_id, t.author, extract(epoch FROM t.at)::float8, t.follows, t.answers, t.text, "
        "t.source, t.visibility FROM turns t JOIN conversations c ON c.id = t.conversation_id "
        "WHERE t.household_id = %s AND c.thread = %s AND t.conversation_id BETWEEN %s AND %s ORDER BY t.id",
        (household_id, f"bench:{bench_id}", first, last))).fetchall()
    return tuple(Said(*r) for r in rows)


async def looks(conn: AsyncConnection[Any], bench_id: int, first: int) -> tuple[Look, ...]:
    """Her looks on the bench in conversations from `first` on."""
    rows = await (await conn.execute(
        "SELECT turn_id, piece_id, extract(epoch FROM looked_at)::float8 FROM bench_looks "
        "WHERE bench_id = %s AND conversation_id >= %s ORDER BY id", (bench_id, first))).fetchall()
    return tuple(Look(*r) for r in rows)

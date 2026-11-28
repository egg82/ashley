"""The pieces a turn touched, read from the command log by `By.turn`: nothing is stored beside the commands."""

from typing import Any

from psycopg import AsyncConnection

from .codec import decode_effect
from .commands import Linked, Unlinked, piece_of

Conn = AsyncConnection[tuple[Any, ...]]


async def pieces_by_turn(conn: Conn, bench_id: int, turns: frozenset[int]) -> dict[int, tuple[int, ...]]:
    """For each of `turns` (person turn ids) that has accepted commands on the bench, the sorted ids of the pieces they
    touched: the piece each effect changed, both ends of a link. A command since undone still counts, since the line
    that made it still talks about that piece. A turn with no commands has no entry. One statement, over the bench's
    commands that carry one of `turns`."""
    if not turns:
        return {}
    cur = await conn.execute(
        "SELECT (command->>'turn')::int, effect FROM bench_commands WHERE bench_id = %s AND outcome = 'accepted' "
        "AND (command->>'turn')::int = ANY(%s)", (bench_id, sorted(turns)))
    found: dict[int, set[int]] = {}
    for turn, raw in await cur.fetchall():
        effect = decode_effect(raw)
        ids = [effect.link.from_id, effect.link.to_id] if isinstance(effect, (Linked, Unlinked)) else [piece_of(effect)]
        found.setdefault(int(turn), set()).update(i for i in ids if i is not None)
    return {t: tuple(sorted(ids)) for t, ids in found.items() if ids}

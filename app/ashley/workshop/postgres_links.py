"""The workshop's link rows (`bench_links`, `ashley.workshop.links`), one statement per function, each on a connection
the caller holds in its transaction."""

from typing import Any

from psycopg import AsyncConnection

from .commands import Effect, Linked, Unlinked
from .links import Links, PieceLink

Conn = AsyncConnection[tuple[Any, ...]]


async def held(conn: Conn, bench_id: int) -> Links:
    """Every link the bench holds, those with an end off the layout included: what `decide` judges against."""
    cur = await conn.execute("SELECT from_piece, kind, to_piece FROM bench_links WHERE bench_id = %s", (bench_id,))
    return frozenset(PieceLink(int(r[0]), str(r[1]), int(r[2])) for r in await cur.fetchall())


async def visible(conn: Conn, bench_id: int) -> tuple[PieceLink, ...]:
    """The bench's links whose two ends are both on its layout, by from, kind and to."""
    cur = await conn.execute(
        "SELECT l.from_piece, l.kind, l.to_piece FROM bench_links l "
        "JOIN bench_pieces f ON f.bench_id = l.bench_id AND f.piece_id = l.from_piece AND NOT f.shelved "
        "JOIN bench_pieces t ON t.bench_id = l.bench_id AND t.piece_id = l.to_piece AND NOT t.shelved "
        "WHERE l.bench_id = %s ORDER BY l.from_piece, l.kind, l.to_piece", (bench_id,))
    return tuple(PieceLink(int(r[0]), str(r[1]), int(r[2])) for r in await cur.fetchall())


async def write(conn: Conn, bench_id: int, household_id: int, effect: Effect, seq: int) -> None:
    """Store what accepted command `seq` did to the bench's links: a `Linked` adds its row, an `Unlinked` deletes it,
    any other effect writes nothing."""
    if isinstance(effect, Linked):
        k = effect.link
        await conn.execute(
            "INSERT INTO bench_links (bench_id, household_id, from_piece, kind, to_piece, seq) "
            "VALUES (%s, %s, %s, %s, %s, %s)", (bench_id, household_id, k.from_id, k.kind, k.to_id, seq))
    elif isinstance(effect, Unlinked):
        k = effect.link
        await conn.execute("DELETE FROM bench_links WHERE bench_id = %s AND from_piece = %s AND kind = %s AND to_piece = %s",
                           (bench_id, k.from_id, k.kind, k.to_id))

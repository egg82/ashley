"""The SQL of a bench's measured site frames (`workshop.SiteFrame`), one statement per function, each on a connection the
caller holds."""

from typing import Any

from psycopg import AsyncConnection

from .workshop import SiteFrame

Conn = AsyncConnection[tuple[Any, ...]]


async def site_frames(conn: Conn, bench_id: int) -> dict[str, SiteFrame]:
    """Every measured address of the bench, by address."""
    cur = await conn.execute("SELECT url, frameable, title FROM bench_site_frames WHERE bench_id = %s", (bench_id,))
    return {str(r[0]): SiteFrame(r[1], str(r[2])) for r in await cur.fetchall()}


async def record(conn: Conn, household_id: int, bench_id: int, url: str, frame: SiteFrame) -> None:
    """Keep `frame` as the measure of `url`, and drop the bench's measures of addresses no piece holds any more."""
    await conn.execute(
        "INSERT INTO bench_site_frames (bench_id, household_id, url, frameable, title) VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (bench_id, url) DO UPDATE SET frameable = EXCLUDED.frameable, title = EXCLUDED.title, "
        "checked_at = now()", (bench_id, household_id, url, frame.frameable, frame.title))
    await conn.execute(
        "DELETE FROM bench_site_frames f WHERE f.bench_id = %s AND NOT EXISTS "
        "(SELECT 1 FROM bench_pieces p WHERE p.bench_id = f.bench_id AND btrim(p.body) = f.url)", (bench_id,))

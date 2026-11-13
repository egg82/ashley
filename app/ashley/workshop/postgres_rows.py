"""The workshop's SQL, one statement per function, each on a connection the caller holds in its transaction."""

from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from .codec import decode_command, decode_effect, encode_command, encode_effect
from .commands import Command, Effect, Pointed, Renamed, Shown, ShownRow, piece_of
from .decide import Accepted, Decision
from .model import Bench, By, Change, Owner, Piece, Place, Text
from .undo_walk import Step
from .workshop import Logged, Placed, Pointer

Conn = AsyncConnection[tuple[Any, ...]]
_BENCH = ("id, household_id, owner_id, title, opened_at, closed_at, next_seq, "
          "(SELECT count(*) FROM bench_pieces p WHERE p.bench_id = benches.id AND NOT p.shelved), "
          "(SELECT max(c.at) FROM bench_commands c WHERE c.bench_id = benches.id AND c.outcome = 'accepted' "
          "AND c.command->>'type' NOT IN ('cue', 'point', 'surfaced')), work")
_PIECE = "piece_id, kind, title, body, version, place_order, place_size, changed_by, outside"
_LOGGED = "seq, at, person_id, command, outcome, effect"


def _utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC)


def _bench(row: tuple[Any, ...]) -> Bench:
    return Bench(row[0], row[1], row[2], row[3], _utc(row[4]), None if row[5] is None else _utc(row[5]),
                 int(row[7]), None if row[8] is None else _utc(row[8]), row[9])


async def insert_bench(conn: Conn, owner: Owner, title: str) -> Bench:
    cur = await conn.execute(f"INSERT INTO benches (household_id, owner_id, title) VALUES (%s, %s, %s) RETURNING {_BENCH}",
                             (owner.household_id, owner.person_id, title))
    row = await cur.fetchone()
    assert row is not None
    return _bench(row)


async def open_benches(conn: Conn, owner: Owner) -> list[Bench]:
    cur = await conn.execute(
        f"SELECT {_BENCH} FROM benches WHERE household_id = %s AND owner_id = %s AND closed_at IS NULL "
        "ORDER BY opened_at DESC, id DESC", (owner.household_id, owner.person_id))
    return [_bench(r) for r in await cur.fetchall()]


async def closed_benches(conn: Conn, owner: Owner) -> list[Bench]:
    cur = await conn.execute(
        f"SELECT {_BENCH} FROM benches WHERE household_id = %s AND owner_id = %s AND closed_at IS NOT NULL "
        "ORDER BY closed_at DESC, id DESC", (owner.household_id, owner.person_id))
    return [_bench(r) for r in await cur.fetchall()]


async def bench(conn: Conn, owner: Owner, bench_id: int, lock: bool = False) -> tuple[Bench, int] | None:
    """The owner's bench and its next seq; locked for this transaction when `lock`."""
    cur = await conn.execute(
        f"SELECT {_BENCH} FROM benches WHERE id = %s AND household_id = %s AND owner_id = %s"
        + (" FOR UPDATE" if lock else ""), (bench_id, owner.household_id, owner.person_id))
    row = await cur.fetchone()
    return None if row is None else (_bench(row), int(row[6]))


async def close_bench(conn: Conn, bench_id: int) -> Bench | None:
    """Closes it now when open; None when it was already closed."""
    cur = await conn.execute(
        f"UPDATE benches SET closed_at = now() WHERE id = %s AND closed_at IS NULL RETURNING {_BENCH}", (bench_id,))
    row = await cur.fetchone()
    return None if row is None else _bench(row)


async def write_title(conn: Conn, bench_id: int, title: str) -> None:
    await conn.execute("UPDATE benches SET title = %s WHERE id = %s", (title, bench_id))


async def write_work(conn: Conn, bench_id: int, work: str | None) -> None:
    await conn.execute("UPDATE benches SET work = %s WHERE id = %s", (work, bench_id))


async def reopen_bench(conn: Conn, bench_id: int) -> Bench | None:
    """Opens it again when closed; None when it was already open."""
    cur = await conn.execute(
        f"UPDATE benches SET closed_at = NULL WHERE id = %s AND closed_at IS NOT NULL RETURNING {_BENCH}", (bench_id,))
    row = await cur.fetchone()
    return None if row is None else _bench(row)


def _piece(row: tuple[Any, ...]) -> Piece:
    return Piece(row[0], row[1], Text(row[2], row[3]), row[4], Place(row[5], row[6]), row[7], bool(row[8]))


async def pieces(conn: Conn, bench_id: int) -> tuple[Piece, ...]:
    """The pieces on the bench's layout, in order."""
    cur = await conn.execute(
        f"SELECT {_PIECE} FROM bench_pieces WHERE bench_id = %s AND NOT shelved ORDER BY place_order", (bench_id,))
    return tuple(_piece(r) for r in await cur.fetchall())


async def of_kind(conn: Conn, household_id: int, kind: str) -> tuple[Placed, ...]:
    """The pieces of `kind` on the layout of the household's open benches, by bench and piece id."""
    cur = await conn.execute(
        "SELECT p.bench_id, b.owner_id, p.piece_id, p.version, p.body FROM bench_pieces p "
        "JOIN benches b ON b.id = p.bench_id AND b.household_id = p.household_id "
        "WHERE p.household_id = %s AND p.kind = %s AND NOT p.shelved AND b.closed_at IS NULL AND b.owner_id IS NOT NULL "
        "ORDER BY p.bench_id, p.piece_id", (household_id, kind))
    return tuple(Placed(int(r[0]), int(r[1]), int(r[2]), int(r[3]), r[4]) for r in await cur.fetchall())


async def shelf(conn: Conn, bench_id: int) -> tuple[Piece, ...]:
    """The bench's shelved pieces, the most recently archived first (an archive is a shelved piece's `changed_by`)."""
    cur = await conn.execute(
        f"SELECT {_PIECE} FROM bench_pieces WHERE bench_id = %s AND shelved ORDER BY changed_by DESC", (bench_id,))
    return tuple(_piece(r) for r in await cur.fetchall())


async def changes(conn: Conn, bench_id: int) -> dict[int, Change]:
    """Each piece's last change, by piece id: the command in `changed_by`, whenever it was."""
    cur = await conn.execute(
        "SELECT p.piece_id, c.at, c.person_id FROM bench_pieces p "
        "JOIN bench_commands c ON c.bench_id = p.bench_id AND c.seq = p.changed_by WHERE p.bench_id = %s", (bench_id,))
    return {int(r[0]): Change(_utc(r[1]), By(r[2])) for r in await cur.fetchall()}


async def pointers(conn: Conn, bench_id: int) -> dict[int, Pointer]:
    """Each piece's latest accepted Point that put a passage up, by piece id: what a screen highlights while the piece is
    still at that version. A later Point that took the highlight away leaves the piece with none."""
    cur = await conn.execute(
        "SELECT DISTINCT ON (effect->>'piece_id') seq, effect FROM bench_commands WHERE bench_id = %s "
        "AND outcome = 'accepted' AND command->>'type' = 'point' ORDER BY effect->>'piece_id', seq DESC", (bench_id,))
    found: dict[int, Pointer] = {}
    for seq, raw in await cur.fetchall():
        effect = decode_effect(raw)
        if isinstance(effect, Pointed) and effect.passage is not None:
            found[effect.piece_id] = Pointer(int(seq), effect.version, effect.passage)
    return found


async def surfaced(conn: Conn, bench_id: int) -> frozenset[tuple[int, ShownRow]]:
    """Every (piece id, row) an accepted Surfaced of the bench named, however old."""
    cur = await conn.execute(
        "SELECT effect FROM bench_commands WHERE bench_id = %s AND outcome = 'accepted' AND command->>'type' = 'surfaced'",
        (bench_id,))
    found: set[tuple[int, ShownRow]] = set()
    for (raw,) in await cur.fetchall():
        effect = decode_effect(raw)
        if isinstance(effect, Shown):
            found.update((effect.piece_id, r) for r in effect.rows)
    return frozenset(found)


async def effect_of(conn: Conn, bench_id: int, seq: int) -> Effect | None:
    cur = await conn.execute("SELECT effect FROM bench_commands WHERE bench_id = %s AND seq = %s AND effect IS NOT NULL",
                             (bench_id, seq))
    row = await cur.fetchone()
    return None if row is None else decode_effect(row[0])


async def steps(conn: Conn, bench_id: int, latest: int) -> list[Step]:
    """The bench's last `latest` commands as the undo walk reads them, oldest first."""
    cur = await conn.execute(
        "SELECT seq, outcome = 'accepted', CASE WHEN command->>'type' = 'undo' THEN command->>'seq' END, "
        "command->>'type' IN ('run', 'propose', 'cue', 'point', 'surfaced') FROM bench_commands WHERE bench_id = %s ORDER BY seq DESC LIMIT %s",
        (bench_id, latest))
    return [Step(int(r[0]), bool(r[1]), None if r[2] is None else int(r[2]), bool(r[3]))
            for r in reversed(await cur.fetchall())]


async def undo_context(conn: Conn, bench_id: int, seq: int) -> tuple[dict[int, Effect], dict[int, int]]:
    """What `decide` reads to judge an Undo of command `seq`: the effects of `seq` and of every accepted command after
    it on the same piece, and which of those are undos, mapped to what they undid. Empty when `seq` has no effect."""
    done = await effect_of(conn, bench_id, seq)
    if done is None:
        return {}, {}
    if isinstance(done, Renamed):
        cur = await conn.execute(
            "SELECT seq, effect, command FROM bench_commands WHERE bench_id = %s AND seq >= %s AND effect IS NOT NULL "
            "AND effect->>'type' = 'renamed' ORDER BY seq", (bench_id, seq))
    else:
        cur = await conn.execute(
            "SELECT seq, effect, command FROM bench_commands WHERE bench_id = %s AND seq >= %s AND effect IS NOT NULL "
            "AND COALESCE(effect->>'piece_id', effect->'piece'->>'id') = %s ORDER BY seq",
            (bench_id, seq, str(piece_of(done))))
    found = await cur.fetchall()
    return ({int(r[0]): decode_effect(r[1]) for r in found},
            {int(r[0]): int(r[2]["seq"]) for r in found if r[2]["type"] == "undo"})


async def install_context(conn: Conn, bench_id: int, piece_id: int, proposal: int) -> dict[int, Effect]:
    """What `decide` reads to judge an Install of piece `piece_id` naming `proposal`: the effects of the piece's accepted
    commands from `proposal` on."""
    cur = await conn.execute(
        "SELECT seq, effect FROM bench_commands WHERE bench_id = %s AND seq >= %s AND effect IS NOT NULL "
        "AND effect->>'piece_id' = %s ORDER BY seq", (bench_id, proposal, str(piece_id)))
    return {int(r[0]): decode_effect(r[1]) for r in await cur.fetchall()}


async def install_effects(conn: Conn, bench_id: int) -> dict[int, Effect]:
    """The effects of the bench's accepted Propose and Install commands, by seq."""
    cur = await conn.execute(
        "SELECT seq, effect FROM bench_commands WHERE bench_id = %s AND outcome = 'accepted' "
        "AND command->>'type' IN ('propose', 'install')", (bench_id,))
    return {int(r[0]): decode_effect(r[1]) for r in await cur.fetchall()}


async def record(conn: Conn, bench_id: int, household_id: int, command: Command, decision: Decision) -> None:
    """The command's log row and the bench's next seq."""
    accepted = isinstance(decision, Accepted)
    await conn.execute(
        "INSERT INTO bench_commands (bench_id, household_id, seq, person_id, command, outcome, effect) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (bench_id, household_id, decision.seq, command.by.person_id, Jsonb(encode_command(command)),
         "accepted" if accepted else decision.reason, Jsonb(encode_effect(decision.effect)) if accepted else None))
    await conn.execute("UPDATE benches SET next_seq = %s WHERE id = %s", (decision.state.next_seq, bench_id))


Stored = tuple[tuple[Piece, ...], tuple[Piece, ...]]
"""A bench's pieces as stored: those on its layout, and those on its shelf."""


async def write_pieces(conn: Conn, bench_id: int, household_id: int, before: Stored, after: Stored) -> None:
    """Make the stored pieces `after`, touching only those that differ from `before`, shelf or layout."""
    was = {(p, bool(shelved)) for shelved, side in enumerate(before) for p in side}
    now = [(p, bool(shelved)) for shelved, side in enumerate(after) for p in side]
    kept = {p.id for p, _ in now}
    gone = [p.id for p, _ in was if p.id not in kept]
    if gone:
        await conn.execute("DELETE FROM bench_pieces WHERE bench_id = %s AND piece_id = ANY(%s)", (bench_id, gone))
    for p, shelved in now:
        if (p, shelved) in was:
            continue
        await conn.execute(
            f"INSERT INTO bench_pieces (bench_id, household_id, {_PIECE}, shelved) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (bench_id, piece_id) DO UPDATE SET title = excluded.title, body = excluded.body, "
            "version = excluded.version, place_order = excluded.place_order, place_size = excluded.place_size, "
            "changed_by = excluded.changed_by, outside = excluded.outside, shelved = excluded.shelved",
            (bench_id, household_id, p.id, p.kind, p.text.title, p.text.body, p.version, p.place.order,
             p.place.size, p.changed_by, p.outside, shelved))


def _logged(row: tuple[Any, ...]) -> Logged:
    effect = None if row[5] is None else decode_effect(row[5])
    return Logged(row[0], _utc(row[1]), decode_command(row[3], By(row[2])), row[4],
                  None if effect is None else piece_of(effect))


async def logged(conn: Conn, bench_id: int, latest: int | None = None) -> list[Logged]:
    """The bench's commands in seq order: all of them, or the `latest` few."""
    if latest is None:
        cur = await conn.execute(f"SELECT {_LOGGED} FROM bench_commands WHERE bench_id = %s ORDER BY seq", (bench_id,))
        return [_logged(r) for r in await cur.fetchall()]
    cur = await conn.execute(f"SELECT {_LOGGED} FROM bench_commands WHERE bench_id = %s ORDER BY seq DESC LIMIT %s",
                             (bench_id, latest))
    return [_logged(r) for r in reversed(await cur.fetchall())]

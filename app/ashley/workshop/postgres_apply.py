"""Deciding one command on a bench whose row the caller holds locked, and storing what it decided: the part of a
command that is the same for a person's bench and a device's screen."""

from typing import Any

from psycopg import AsyncConnection

from . import postgres_links, postgres_rows as rows
from .commands import Command, Install, Link, Renamed, Undo, Unlink
from .decide import Accepted, BenchState, Decision, decide
from .links import Links
from .rules import Rules

Conn = AsyncConnection[tuple[Any, ...]]


async def decided(conn: Conn, bench_id: int, household_id: int, next_seq: int, title: str, command: Command,
                  rules: Rules) -> Decision:
    """`command` decided against the bench as it stands and logged as its next `seq`, with the pieces (and title and
    links) it changed written, in the caller's transaction."""
    before = (await rows.pieces(conn, bench_id), await rows.shelf(conn, bench_id))
    effects, undos = ({}, {})
    if isinstance(command, Undo) and command.seq >= next_seq - rules.undo_window:
        effects, undos = await rows.undo_context(conn, bench_id, command.seq)
    elif isinstance(command, Install):
        effects = await rows.install_context(conn, bench_id, command.piece_id, command.proposal)
    links: Links = await postgres_links.held(conn, bench_id) if isinstance(command, (Link, Unlink, Undo)) else frozenset()
    decision = decide(BenchState(before[0], next_seq, effects, undos, before[1], title, links), command, rules)
    await rows.record(conn, bench_id, household_id, command, decision)
    if isinstance(decision, Accepted):
        await rows.write_pieces(conn, bench_id, household_id, before, (decision.state.pieces, decision.state.shelf))
        await postgres_links.write(conn, bench_id, household_id, decision.effect, decision.seq)
        if isinstance(decision.effect, Renamed):
            await rows.write_title(conn, bench_id, decision.state.title)
    return decision

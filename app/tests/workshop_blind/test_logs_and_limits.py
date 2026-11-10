"""What the workshop writes to the logs (ids, kinds, outcomes, never a title or a body), and the shipped limits at their
edges through the real service."""

import re
from collections.abc import Callable, Coroutine
from typing import Any

import pytest
from ashley import logs
from ashley.workshop import rules as workshop_rules
from ashley.workshop.model import HER, By, Text
from ashley.workshop.workshop import BenchClosed, BenchNotFound
from blind_support import add, edit, move, remove, undo
from contract.conversations_support import events, run
from service_support import workshop, world

TITLE = "PLANTED-TITLE-q7"
BODY = "PLANTED-BODY-q7"
NEW = "PLANTED-EDIT-q7"


def test_logs_carry_ids_and_outcomes_never_a_title_or_a_body(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "debug"})
    w = world(db_url)
    capsys.readouterr()
    me = By(w.alana.person_id)

    async def scenario() -> int:
        async with workshop(db_url, workshop_rules.load()) as s:
            bench = await s.open(w.alana, TITLE)
            await s.apply(w.alana, bench.id, add(TITLE, BODY, by=me))
            await s.apply(w.alana, bench.id, add(TITLE, BODY, kind="hologram", by=me))        # refused
            await s.apply(w.alana, bench.id, edit(2, 1, NEW, NEW, me))                   # refused: no such piece
            await s.apply(w.alana, bench.id, edit(1, 1, NEW, NEW, me))
            await s.apply(w.alana, bench.id, edit(1, 1, NEW, NEW, me))                   # stale
            await s.apply(w.alana, bench.id, add(TITLE, BODY, by=HER))
            await s.apply(w.alana, bench.id, move(2, 0, "full", me))
            await s.apply(w.alana, bench.id, undo(1, me))                                 # changed_since
            await s.apply(w.alana, bench.id, remove(2, me))
            await s.read(w.alana, bench.id)
            await s.log(w.alana, bench.id)
            await s.open_benches(w.alana)
            await s.close(w.alana, bench.id)
            with pytest.raises(BenchClosed):
                await s.apply(w.alana, bench.id, add(TITLE, BODY, by=me))
            with pytest.raises(BenchNotFound):
                await s.apply(w.sam, bench.id, add(TITLE, BODY, by=By(w.sam.person_id)))
            return bench.id

    bench_id = run_returning(scenario)
    out = capsys.readouterr().out
    for planted in (TITLE, BODY, NEW):
        assert planted not in out
    commands = events(out, "workshop.command")
    assert len(commands) == 9 and len(events(out, "workshop.opened")) == 1 and len(events(out, "workshop.closed")) == 1
    text = "\n".join(line for line in out.splitlines() if "workshop.command" in line)
    for word in ("accepted", "unknown_kind", "no_such_piece", "stale_base", "changed_since", "person", "ashley", "edit",
                 "move", "undo", "remove", "add"):
        assert re.search(rf"\b{word}\b", text), word
    assert all(re.search(rf"\b{bench_id}\b", line) for line in out.splitlines() if "workshop." in line)


def run_returning(scenario: Callable[[], Coroutine[Any, Any, int]]) -> int:
    box: list[int] = []

    async def wrapped() -> None:
        box.append(await scenario())

    run(wrapped())
    return box[0]


def test_the_shipped_limits_hold_at_their_edges_through_the_real_service(db_url: str) -> None:
    rules = workshop_rules.load()
    w = world(db_url)
    me = By(w.alana.person_id)

    async def scenario() -> None:
        async with workshop(db_url, rules) as s:
            bench = await s.open(w.alana, "t" * rules.title_max_chars)
            big = "ü" * rules.kinds["document"].max_chars
            got = await s.apply(w.alana, bench.id, add("t" * rules.title_max_chars, big, "document", by=me))
            assert got.outcome == "accepted"
            assert (await s.apply(w.alana, bench.id, add("a", big + "x", "document", by=me))).outcome == "too_long"
            assert (await s.apply(w.alana, bench.id, add("a", "n" * (rules.kinds["note"].max_chars + 1), by=me))
                    ).outcome == "too_long"
            assert (await s.apply(w.alana, bench.id, add("a", "n" * rules.kinds["note"].max_chars, by=me))).outcome == "accepted"
            assert (await s.apply(w.alana, bench.id, add("t" * (rules.title_max_chars + 1), by=me))).outcome == "bad_title"
            view = await s.read(w.alana, bench.id)
            assert view.pieces[0].text == Text("t" * rules.title_max_chars, big) and len(view.bench.title) == 120

    run(scenario())


def test_the_pieces_limit_is_the_shipped_one(db_url: str) -> None:
    rules = workshop_rules.load()
    w = world(db_url)
    me = By(w.alana.person_id)

    async def scenario() -> None:
        async with workshop(db_url, rules) as s:
            bench = await s.open(w.alana, "t")
            outcomes = [(await s.apply(w.alana, bench.id, add("p", by=me))).outcome for _ in range(rules.max_pieces + 1)]
            assert outcomes == ["accepted"] * rules.max_pieces + ["full"]
            assert len((await s.read(w.alana, bench.id)).pieces) == rules.max_pieces
            assert len((await s.read(w.alana, bench.id)).recent) == min(rules.max_pieces + 1, rules.recent_commands)

    run(scenario())


def test_whitespace_in_titles_and_bodies_is_kept_exactly(db_url: str) -> None:
    w = world(db_url)
    me = By(w.alana.person_id)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench = await s.open(w.alana, " t ")
            await s.apply(w.alana, bench.id, add(" a ", " x\n ", by=me))
            await s.apply(w.alana, bench.id, edit(1, 1, "b ", "\n\ty", me))
            view = await s.read(w.alana, bench.id)
            assert view.bench.title == " t " and view.pieces[0].text == Text("b ", "\n\ty")
            assert (await s.log(w.alana, bench.id))[0].command == add(" a ", " x\n ", by=me)

    run(scenario())


def test_a_closed_bench_of_anothers_is_as_absent_as_an_open_one(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench = await s.open(w.alana, "t")
            await s.close(w.alana, bench.id)
            for who in (w.sam, w.zed):
                for call in (s.read(who, bench.id), s.log(who, bench.id), s.close(who, bench.id)):
                    with pytest.raises(BenchNotFound):
                        await call

    run(scenario())

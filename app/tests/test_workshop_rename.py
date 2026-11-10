"""Renaming a bench is a Command like any change: decided by `decide` (refused `bad_title` for an empty or too long
name), stored on the bench, undone by an Undo, replayed from the log, announced on Live, and offered to her as
`bench_rename`."""

import asyncio
import json

import pytest
from ashley import services
from ashley.inference.model import ToolCall
from ashley.workshop.commands import Rename, Renamed, Undo, type_of
from ashley.workshop.decide import Accepted, BenchState, Refused, decide, replay
from ashley.workshop.model import HER, By, Owner
from ashley.workshop.workshop import Applied, Workshop
from bench_tools_support import FakeWorkshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from test_bench_tools import tools
from test_workshop_decide import ALANA, RULES as DECIDE_RULES, add
from test_workshop_postgres import people, run, workshop_on


def test_a_rename_is_accepted_into_the_bench_title_and_says_what_it_was() -> None:
    got = decide(BenchState(title="old"), Rename(HER, "new"), DECIDE_RULES)
    assert isinstance(got, Accepted) and got.effect == Renamed("old", "new") and got.state.title == "new"
    assert got.state.pieces == () and got.seq == 1 and type_of(Rename(HER, "x")) == "rename"


@pytest.mark.parametrize("title", ["", "  ", "toolong"])
def test_an_empty_or_too_long_name_is_refused_bad_title(title: str) -> None:
    got = decide(BenchState(title="old"), Rename(HER, title), DECIDE_RULES)
    assert isinstance(got, Refused) and got.reason == "bad_title" and got.state.title == "old"
    assert got.state.next_seq == 2


def test_a_name_is_kept_without_the_space_around_it() -> None:
    got = decide(BenchState(title="old"), Rename(HER, " new "), DECIDE_RULES)
    assert isinstance(got, Accepted) and got.state.title == "new"


def test_an_undo_of_a_rename_puts_the_name_back_and_a_rename_after_it_blocks_the_undo() -> None:
    undo = replay([Rename(HER, "one"), Rename(ALANA, "two"), Undo(ALANA, 2)], DECIDE_RULES)[-1]
    assert isinstance(undo, Accepted) and undo.state.title == "one"
    blocked = replay([Rename(HER, "one"), Rename(ALANA, "two"), Undo(ALANA, 1)], DECIDE_RULES)[-1]
    assert isinstance(blocked, Refused) and blocked.reason == "changed_since"


def test_a_replay_seeded_with_the_opening_title_undoes_a_rename_back_to_it() -> None:
    log = [Rename(HER, "one"), Rename(ALANA, "two"), Undo(ALANA, 2), Undo(ALANA, 1)]
    decisions = replay(log, DECIDE_RULES, title="open")
    assert [d.state.title for d in decisions] == ["one", "two", "one", "open"]
    assert all(isinstance(d, Accepted) for d in decisions)
    unseeded = replay(log, DECIDE_RULES)
    assert unseeded[-1].state.title == ""


def test_a_rename_does_not_touch_the_pieces_or_their_undo() -> None:
    got = replay([add("a"), Rename(HER, "named"), Undo(ALANA, 1)], DECIDE_RULES)
    assert isinstance(got[-1], Accepted) and got[-1].state.pieces == ()


def test_the_stored_title_changes_with_an_accepted_rename_and_is_logged_and_undone(db_url: str) -> None:
    alana, _, _ = people(db_url)

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            bench = await shop.open(alana, "ask start")
            done = await shop.apply(alana, bench.id, Rename(HER, "A book"))
            assert done == Applied(1, "accepted", None)
            view = await shop.read(alana, bench.id)
            assert view.bench.title == "A book" and [r.piece_id for r in view.recent] == [None]
            assert (await shop.apply(alana, bench.id, Rename(HER, " "))).outcome == "bad_title"
            assert (await shop.read(alana, bench.id)).bench.title == "A book"
            assert (await shop.apply(alana, bench.id, Undo(By(alana.person_id), 1))).outcome == "accepted"
            assert (await shop.read(alana, bench.id)).bench.title == "ask start"
            with pytest.raises(ValueError):
                await shop.apply(alana, bench.id, Rename(HER, "a\x00b"))
            log = await shop.log(alana, bench.id)
            assert [type_of(r.command) for r in log] == ["rename", "rename", "undo"]

    run(scenario())


def test_she_is_offered_bench_rename_and_it_builds_her_rename_command() -> None:
    shop = FakeWorkshop()
    services.register(Workshop, shop)
    got = asyncio.run(tools().catalogue())
    spec = next(s for s in got.specs if s.name == "bench_rename")
    assert json.loads(json.dumps(spec.parameters))["required"] == ["title"]
    result = asyncio.run(tools().call(ToolCall("c", "bench_rename", {"title": "A book"})))
    assert shop.applied == [(Owner(10, 1), 4, Rename(HER, "A book"))]
    assert json.loads(result.content)["seq"] == 7
    services.unregister(Workshop)


def test_a_title_that_is_not_a_string_is_a_bad_argument_and_reaches_no_bench() -> None:
    shop = FakeWorkshop()
    services.register(Workshop, shop)
    result = asyncio.run(tools().call(ToolCall("c", "bench_rename", {"title": 4})))
    assert shop.applied == [] and "title" in result.content
    services.unregister(Workshop)

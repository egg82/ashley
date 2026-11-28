"""Her link tools over the real Workshop: `bench_add` links the new piece right after adding it, in the same turn;
`bench_link` links and unlinks pieces already there; `bench_read` and the moment show each piece's links; "undo
that" takes a turn's links back with its pieces; a malformed `links` changes nothing."""

import json

from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.inference.model import ToolCall
from ashley.live.live import Live
from ashley.tools import bench_now
from ashley.tools.bench_tools import BenchTools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.links import PieceLink
from ashley.workshop.model import Owner
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run
from live_support import FakeLive

RULES = workshop_rules.load()


def note(title: str, **more: object) -> dict[str, object]:
    return {"kind": "note", "title": title, "body": "", **more}


def test_her_add_links_the_new_piece_and_her_link_tool_links_and_unlinks(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        services.register(Live, FakeLive())
        services.register(Workshop, PostgresWorkshop(database, RULES))
        try:
            shop = services.get(Workshop)
            bench = (await shop.open(alana, "shed")).id
            hers = BenchTools(home, alana.person_id, bench, turn_id=41)
            await hers.call(ToolCall("a", "bench_add", note("Plan")))
            await hers.call(ToolCall("b", "bench_add", note("Wood")))
            added = await hers.call(ToolCall("c", "bench_add", note("Cut list", links=[
                {"kind": "part_of", "to": 1}, {"kind": "depends_on", "to": 2}, {"kind": "part_of", "to": 9}])))
            assert not added.is_error, added.content
            body = json.loads(added.content)
            assert body["piece_id"] == 3 and body["links"][:2] == [{"kind": "part_of", "to": 1, "seq": 4},
                                                                     {"kind": "depends_on", "to": 2, "seq": 5}]
            assert body["links"][2]["refused"] == "no_such_piece"
            linked = await hers.call(ToolCall("d", "bench_link", {"from_id": 2, "kind": "part_of", "to_id": 1}))
            assert not linked.is_error, linked.content
            again = await hers.call(ToolCall("e", "bench_link", {"from_id": 2, "kind": "part_of", "to_id": 1}))
            assert again.is_error and again.content.startswith("already_linked:")
            gone = await hers.call(ToolCall("f", "bench_link", {"from_id": 3, "kind": "depends_on", "to_id": 2,
                                                              "unlink": True}))
            assert not gone.is_error, gone.content
            view = await shop.read(alana, bench)
            assert view.links == (PieceLink(2, "part_of", 1), PieceLink(3, "part_of", 1))
            read = json.loads((await hers.call(ToolCall("g", "bench_read", {}))).content)
            assert [p.get("links") for p in read["pieces"]] == [None, [{"kind": "part_of", "to": 1}],
                                                                [{"kind": "part_of", "to": 1}]]
            assert '"links": [{"kind": "part_of", "to": 1}]' in bench_now.now(view, RULES, 100)
            log = await shop.log(alana, bench)
            assert {row.command.by.turn for row in log} == {41} and log[3].command.by.person_id is None
        finally:
            await database.close()

    run(scenario())


def test_undoing_her_turn_takes_its_links_back_and_a_bad_links_argument_changes_nothing(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        services.register(Live, FakeLive())
        services.register(Workshop, PostgresWorkshop(database, RULES))
        try:
            shop = services.get(Workshop)
            bench = (await shop.open(alana, "shed")).id
            await BenchTools(home, alana.person_id, bench, turn_id=1).call(ToolCall("a", "bench_add", note("Plan")))
            turn = BenchTools(home, alana.person_id, bench, turn_id=2)
            for bad in ({"kind": "part_of"}, "part_of", {"kind": "part_of", "to": 1, "why": "x"}):
                refused = await turn.call(ToolCall("b", "bench_add", note("Step", links=[bad])))
                assert refused.is_error and refused.content.startswith("bad_arguments:")
            assert len(await shop.log(alana, bench)) == 1
            await turn.call(ToolCall("c", "bench_add", note("Step", links=[{"kind": "version_of", "to": 1}])))
            assert (await shop.read(alana, bench)).links == (PieceLink(2, "version_of", 1),)
            undone = await turn.call(ToolCall("d", "bench_undo", {"seq": 2, "whole_turn": True}))
            assert json.loads(undone.content) == {"undone": [3, 2]}
            view = await shop.read(alana, bench)
            assert [p.text.title for p in view.pieces] == ["Plan"] and view.links == ()
        finally:
            await database.close()

    run(scenario())

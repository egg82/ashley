"""Her tools and a person's pins over the real Workshop: no tool of hers offers a pin or a box, so `bench_move` refuses
one; her move of a pinned piece keeps the person's pin and box; `bench_read` and the moment say `pinned` for a pinned
piece and nothing for another."""

import json

from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.inference.model import ToolCall
from ashley.live.live import Live
from ashley.tools import bench_now
from ashley.tools.bench_specs import specs
from ashley.tools.bench_tools import BenchTools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Move
from ashley.workshop.model import Box, By, Owner, Pin, Place
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run
from live_support import FakeLive

RULES = workshop_rules.load()


def note(title: str) -> dict[str, object]:
    return {"kind": "note", "title": title, "body": ""}


def test_no_tool_of_hers_offers_a_pin_or_a_box() -> None:
    for spec in specs(RULES):
        assert not {"pin", "box"} & set(json.dumps(spec.parameters).replace('"', " ").split()), spec.name


def test_her_move_keeps_a_persons_pin_and_box_and_her_read_says_pinned(db_url: str) -> None:
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
            hers = BenchTools(home, alana.person_id, bench, turn_id=3)
            await hers.call(ToolCall("a", "bench_add", note("Plan")))
            await hers.call(ToolCall("b", "bench_add", note("Wood")))
            pinned = Move(By(alana.person_id), 1, Place(0, "small"), Pin(-200, 60), Box(480, 320))
            assert (await shop.apply(alana, bench, pinned)).outcome == "accepted"
            await hers.call(ToolCall("c", "bench_edit", {"piece_id": 1, "base_version": 1, "title": "Plan",
                                                         "body": "measure twice"}))
            sneaky = await hers.call(ToolCall("d", "bench_move", {"piece_id": 1, "order": 1, "size": "full",
                                                                  "pin": None}))
            assert sneaky.is_error and sneaky.content.startswith("bad_arguments:")
            moved = await hers.call(ToolCall("e", "bench_move", {"piece_id": 1, "order": 1, "size": "full"}))
            assert not moved.is_error, moved.content
            view = await shop.read(alana, bench)
            assert view.pieces[1].place == Place(1, "full", Pin(-200, 60), Box(480, 320))
            read = json.loads((await hers.call(ToolCall("f", "bench_read", {}))).content)
            assert [(p["id"], p.get("pinned"), p["last_changed_by"]) for p in read["pieces"]] == [
                (2, None, "you"), (1, True, "you")]
            assert '"pinned": true' in bench_now.now(view, RULES, 100)
        finally:
            await database.close()

    run(scenario())

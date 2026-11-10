"""The tidy pass over a real bench: it asks the model only when a text piece changed, keeps what the model pointed at that
is really there, never loses it to a restart, and offers it to her until it is dismissed or fixed."""

import asyncio

import pytest
from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.tidy import run
from ashley.tidy.config import load as load_config
from ashley.tidy.offer import to_check
from ashley.tidy.postgres import PostgresTidy
from ashley.workshop.commands import Edit, Move
from ashley.workshop.model import By, Place, Text
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from tidy_support import HEADER, Bench, add, scenario, two_notes

CONFIG = load_config()


async def kept(bench: Bench) -> list[tuple[int, str, int | None]]:
    return [(f.piece_id, f.kind, f.by_piece_id) for f in await bench.tidy.findings(bench.id) if not f.dismissed]


def test_a_changed_text_piece_is_checked_and_only_the_quotes_that_are_there_are_kept(db_url: str) -> None:
    async def body(bench: Bench) -> None:
        status, decompile = await two_notes(bench)
        await run.after_turn(bench.owner, bench.id)
        assert [task for task, _ in bench.inference.asked] == ["bench_tidy"]
        assert await kept(bench) == [(status, "debris", None), (status, "superseded", decompile),
                                     (decompile, "contradicts", status)]

    scenario(db_url, body)


def test_nothing_is_asked_again_until_a_text_piece_changes(db_url: str) -> None:
    async def body(bench: Bench) -> None:
        status, decompile = await two_notes(bench)
        shop = services.get(Workshop)
        await run.after_turn(bench.owner, bench.id)
        await run.after_turn(bench.owner, bench.id)
        assert len(bench.inference.asked) == 1                          # same versions: nothing changed
        await shop.apply(bench.owner, bench.id, Move(By(bench.owner.person_id), decompile, Place(0, "full")))
        await add(bench, "site", Text("ref", "https://example.com/a"))
        await run.after_turn(bench.owner, bench.id)
        assert len(bench.inference.asked) == 1                          # a move and a site piece are no text change
        await shop.apply(bench.owner, bench.id, Edit(By(bench.owner.person_id), status, 1, Text("t", "now\n" + HEADER)))
        await run.after_turn(bench.owner, bench.id)
        assert len(bench.inference.asked) == 2                          # an edit is

    scenario(db_url, body)


def test_a_bench_with_no_text_piece_asks_nothing(db_url: str) -> None:
    async def body(bench: Bench) -> None:
        await add(bench, "site", Text("ref", "https://example.com/a"))
        await run.after_turn(bench.owner, bench.id)
        assert bench.inference.asked == []

    scenario(db_url, body)


def test_a_request_every_route_rejected_is_recorded_done_and_not_asked_again_until_a_piece_changes(
        db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def body(bench: Bench) -> None:
        status, decompile = await two_notes(bench)
        bench.inference.rejected = True
        caplog.set_level("INFO", logger="ashley.tidy")
        await run.after_turn(bench.owner, bench.id)
        assert [getattr(r, "fields")["outcome"] for r in caplog.records if r.message == "tidy.pass"] == ["rejected"]
        assert set(await bench.tidy.checked(bench.id)) == {status, decompile} and await kept(bench) == []
        await run.after_turn(bench.owner, bench.id)
        assert len(bench.inference.asked) == 1
        await services.get(Workshop).apply(bench.owner, bench.id,
                                           Edit(By(bench.owner.person_id), status, 1, Text("t", "now\n" + HEADER)))
        await run.after_turn(bench.owner, bench.id)
        assert len(bench.inference.asked) == 2

    scenario(db_url, body)


def test_a_model_out_of_reach_records_nothing_and_the_next_turn_tries_again(db_url: str) -> None:
    async def body(bench: Bench) -> None:
        await two_notes(bench)
        bench.inference.down = True
        await run.after_turn(bench.owner, bench.id)
        assert await bench.tidy.checked(bench.id) == {} and await kept(bench) == []
        bench.inference.down = False
        await run.after_turn(bench.owner, bench.id)
        assert len(bench.inference.asked) == 2 and len(await kept(bench)) == 3

    scenario(db_url, body)


def test_a_pass_already_running_on_the_bench_is_not_doubled(db_url: str) -> None:
    async def body(bench: Bench) -> None:
        await two_notes(bench)
        assert await bench.tidy.begin(bench.owner.household_id, bench.id, CONFIG.lock_s)   # another pod took it
        await run.after_turn(bench.owner, bench.id)
        assert bench.inference.asked == []
        await bench.tidy.release(bench.id)
        await run.after_turn(bench.owner, bench.id)
        assert len(bench.inference.asked) == 1

    scenario(db_url, body)


def test_a_pass_that_never_finished_releases_the_bench_by_age(db_url: str) -> None:
    async def body(bench: Bench) -> None:
        assert await bench.tidy.begin(bench.owner.household_id, bench.id, 60)
        assert not await bench.tidy.begin(bench.owner.household_id, bench.id, 60)
        await asyncio.sleep(1.1)
        assert await bench.tidy.begin(bench.owner.household_id, bench.id, 1)

    scenario(db_url, body)


def test_findings_survive_a_restart_and_a_new_pod_offers_the_same(db_url: str) -> None:
    async def body(bench: Bench) -> None:
        status, decompile = await two_notes(bench)
        await run.after_turn(bench.owner, bench.id)
        database = PoolDatabase(db_url)                                # another pod: nothing carried over in memory
        await database.open()
        try:
            reborn = PostgresTidy(database)
            pieces = (await services.get(Workshop).read(bench.owner, bench.id)).pieces
            offered = await to_check(reborn, bench.id, pieces, CONFIG)
            assert [(o["piece_id"], o["kind"]) for o in offered] == [(status, "debris"), (status, "superseded"),
                                                                      (decompile, "contradicts")]
            assert await reborn.checked(bench.id) == {p.id: p.version for p in pieces}
        finally:
            await database.close()

    scenario(db_url, body)

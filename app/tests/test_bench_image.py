"""Her picture tool end to end: over a real Postgres and the real router and spend ledger with a scripted image model,
the picture is an ordinary image piece (on the bench, its bytes in the object store, hers, undoable), the household's
limit is counted from the ledger and refuses a call before any model is asked, a refusal and a failure come back as
errors that say why, and the log holds no prompt."""

import hashlib
import json
import logging

import pytest
from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.files.intake import key_of
from ashley.files.memory import MemoryStore
from ashley.files.store import NullStore, ObjectStore
from ashley.inference.image_quota import ImageCap, ImageLimit, drawn
from ashley.inference.inference import Inference, NullInference
from ashley.inference.model import Route, Task, ToolCall, ToolResult
from ashley.inference.postgres import PostgresSpendLedger
from catalogue_support import NONE
from ashley.inference.provider import ProviderRefused
from ashley.inference.router import RoutedInference
from ashley.inference.routes import Routes
from ashley.live.live import Live
from ashley.tools.bench_image import BenchImageTools
from ashley.tools.bench_tools import BenchTools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Undo
from ashley.workshop.model import By, Owner
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run, scalar
from image_support import JPEG, ScriptedMaker
from live_support import FakeLive
from speech_support import failing
from typing import get_args

RULES = workshop_rules.load()
LIMIT = 2


def conversation(url: str, home: int) -> int:
    return int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id", (home,)))


async def say(tools: BenchImageTools, args: dict[str, object]) -> ToolResult:
    return await tools.call(ToolCall("c", "bench_make_image", args))


def wire(database: PoolDatabase, *makers: ScriptedMaker) -> MemoryStore:
    text: dict[Task, tuple[Route, ...]] = {t: (Route("none", "m", 1.0),) for t in get_args(Task)}
    routes = Routes(text, 300.0, image={"image": tuple(Route(m.name, f"{m.name}-model", 5.0) for m in makers)})
    cap = ImageCap(lambda household_id, window_s: drawn(database, household_id, window_s), ImageLimit(LIMIT, 86400))
    services.register(Inference, RoutedInference(routes, makers, PostgresSpendLedger(database), NONE,
                                                 image_cap=cap))
    services.register(Live, FakeLive())
    services.register(Workshop, PostgresWorkshop(database, RULES))
    store = MemoryStore()
    services.register(ObjectStore, store)
    return store


def test_the_picture_is_an_ordinary_image_piece_that_is_hers_stored_and_undoable(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))
    talk = conversation(db_url, home)

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        maker = ScriptedMaker("a")
        store = wire(database, maker)
        try:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "shed")
            tools = BenchImageTools(home, alana.person_id, bench.id, talk)
            assert [s.name for s in (await tools.catalogue()).specs] == ["bench_make_image"]

            made = await say(tools, {"prompt": "a lamp", "aspect": "wide", "name": "lamp"})
            assert not made.is_error, made.content
            body = json.loads(made.content)
            assert (body["media_type"], body["size"]) == ("image/jpeg", len(JPEG))
            (piece,) = (await shop.read(alana, bench.id)).pieces
            assert (piece.kind, piece.text.title) == ("image", "lamp.jpg")
            sha = hashlib.sha256(JPEG).hexdigest()
            assert json.loads(piece.text.body)["sha256"] == sha
            assert await store.get(key_of(home, sha)) == JPEG
            assert maker.asked == ["a lamp"]
            seen = json.loads((await BenchTools(home, alana.person_id, bench.id).call(
                ToolCall("r", "bench_read", {}))).content)
            assert [p["kind"] for p in seen["pieces"]] == ["image"]

            assert {row.by.author for row in await shop.log(alana, bench.id)} == {"ashley"}
            await shop.apply(alana, bench.id, Undo(By(alana.person_id), body["seq"]))
            assert (await shop.read(alana, bench.id)).pieces == ()
        finally:
            await database.close()

    run(scenario())


def test_a_household_at_its_limit_is_refused_by_the_tool_and_another_household_is_not(db_url: str) -> None:
    home, other = household(db_url), household(db_url, "other")
    alana, sam = Owner(home, person(db_url, home)), Owner(other, person(db_url, other))
    talk, their_talk = conversation(db_url, home), conversation(db_url, other)

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        maker = ScriptedMaker("a")
        wire(database, maker)
        try:
            shop = services.get(Workshop)
            bench, their_bench = await shop.open(alana, "shed"), await shop.open(sam, "garden")
            tools = BenchImageTools(home, alana.person_id, bench.id, talk)
            for _ in range(LIMIT):
                assert not (await say(tools, {"prompt": "a lamp"})).is_error
            capped = await say(tools, {"prompt": "a lamp"})
            assert capped.is_error and capped.content.startswith("capped:")
            assert len(maker.asked) == LIMIT and len((await shop.read(alana, bench.id)).pieces) == LIMIT
            theirs = BenchImageTools(other, sam.person_id, their_bench.id, their_talk)
            assert not (await say(theirs, {"prompt": "a lamp"})).is_error
        finally:
            await database.close()

    run(scenario())


def test_a_refused_call_counts_and_a_failed_one_does_not(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))
    talk = conversation(db_url, home)

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        wire(database, ScriptedMaker("a", error=failing("unavailable")))
        try:
            bench = await services.get(Workshop).open(alana, "shed")
            tools = BenchImageTools(home, alana.person_id, bench.id, talk)
            await say(tools, {"prompt": "x"})
            assert await drawn(database, home, 86400) == 0
            wire(database, ScriptedMaker("a", error=ProviderRefused("blocked")))
            await say(tools, {"prompt": "x"})
            assert await drawn(database, home, 86400) == 1
        finally:
            await database.close()

    run(scenario())


def test_a_refusal_and_a_failure_come_back_as_errors_that_say_why_and_add_nothing(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))
    talk = conversation(db_url, home)

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        refusing = ScriptedMaker("a", error=ProviderRefused("blocked"))
        wire(database, refusing)
        try:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "shed")
            tools = BenchImageTools(home, alana.person_id, bench.id, talk)
            refused = await say(tools, {"prompt": "x"})
            assert refused.is_error and refused.content.startswith("refused:")

            wire(database, ScriptedMaker("a", error=failing("unavailable")), ScriptedMaker("b", error=failing("error")))
            failed = await say(tools, {"prompt": "x"})
            assert failed.is_error and failed.content.startswith("unavailable:")
            assert "error" in failed.content and "unavailable" in failed.content.split("failure:")[1]

            bad: list[dict[str, object]] = [{}, {"prompt": " "}, {"prompt": "x", "aspect": "round"}, {"prompt": "x", "size": "1"}]
            for args in bad:
                got = await say(tools, args)
                assert got.is_error and got.content.startswith("bad_arguments:"), args
            assert (await shop.read(alana, bench.id)).pieces == ()
        finally:
            await database.close()

    run(scenario())


def test_the_tool_is_not_offered_without_an_object_store_or_an_image_model(db_url: str) -> None:
    async def scenario() -> None:
        services.register(ObjectStore, NullStore())
        services.register(Inference, RoutedInference(Routes({t: (Route("none", "m", 1.0),) for t in get_args(Task)},
                                                            300.0), [], PostgresSpendLedger(PoolDatabase(db_url)),
                                                     NONE))
        assert (await BenchImageTools(1, 1, 1, 1).catalogue()).specs == ()
        services.register(ObjectStore, MemoryStore())
        services.register(Inference, NullInference())
        assert (await BenchImageTools(1, 1, 1, 1).catalogue()).specs == ()

    run(scenario())


def test_the_log_holds_no_prompt(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))
    talk = conversation(db_url, home)
    caplog.set_level(logging.INFO)

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        wire(database, ScriptedMaker("a"))
        try:
            bench = await services.get(Workshop).open(alana, "shed")
            await say(BenchImageTools(home, alana.person_id, bench.id, talk), {"prompt": "a very secret lamp"})
        finally:
            await database.close()

    run(scenario())
    assert any(r.getMessage() == "tools.call" for r in caplog.records)
    assert "secret" not in "\n".join(f"{r.getMessage()} {getattr(r, 'fields', '')}" for r in caplog.records)

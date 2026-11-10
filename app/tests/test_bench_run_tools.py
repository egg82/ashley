"""Her `bench_run` and `bench_last_run` (`ashley.tools.bench_run.BenchRunTools`) over a real database, and where a turn
offers them (`channels.turn_tools.for_turn`): only on a bench's talk with the turn's ids known and a sandbox that runs
some language; a run is a change and a read of the last run is not; what came out and why nothing ran go back to her."""

import asyncio
import json
from dataclasses import replace

import pytest
from bench_run_support import Box, code, note, world
from ashley import services
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import for_turn
from ashley.inference.model import ToolCall, ToolResult
from ashley.runs.sandbox import Sandbox
from ashley.tools.bench_run import BenchRunTools
from ashley.tools.tools import Catalogue, Tools
from ashley.workshop.commands import Run
from ashley.workshop.model import Owner
from ashley.workshop.run_piece import run_piece
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run, scalar

WEB = Inbound(household_id=10, thread="person:1:web", text="hi", kind="chat", medium="text", audience="owner",
              speaker_id=1, shared=False, place=None, channel="web", later=True, later_by="turn")
BENCH = replace(WEB, thread="bench:4", kind="brainstorm", bench_id=4)


class Everyday(Tools):
    async def catalogue(self) -> Catalogue:
        return Catalogue((), None)

    async def call(self, call: ToolCall) -> ToolResult:
        raise NotImplementedError


@pytest.fixture
def everyday() -> object:
    services.register(Tools, Everyday())
    yield
    services.unregister(Tools)


def names(tools: Tools) -> list[str]:
    return [s.name for s in asyncio.run(tools.catalogue()).specs]


def test_only_a_bench_turn_with_its_ids_and_a_sandbox_offers_bench_run(everyday: object) -> None:
    services.register(Sandbox, Box())
    try:
        offered = asyncio.run(for_turn(BENCH, (20, 30)).catalogue()).specs
        run_spec = next(s for s in offered if s.name == "bench_run")
        last_spec = next(s for s in offered if s.name == "bench_last_run")
        assert run_spec.reads is False and last_spec.reads is True
        assert "bench_run" not in names(for_turn(BENCH)) and "bench_run" not in names(for_turn(WEB, (20, 30)))
        assert "bench_run" not in names(for_turn(replace(BENCH, speaker_id=None), (20, 30)))
    finally:
        services.unregister(Sandbox)
    assert "bench_run" not in names(for_turn(BENCH, (20, 30)))


def setting(url: str) -> tuple[Owner, int, int]:
    home = household(url)
    alana = Owner(home, person(url, home))
    conversation = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                              (home,)))
    said = int(scalar(url, "INSERT INTO turns (conversation_id, household_id, author, text) "
                           "VALUES (%s, %s, 'person', 'run it') RETURNING id", (conversation, home)))
    return alana, conversation, said


def test_her_run_returns_what_came_out_and_her_read_shows_the_persons_run(db_url: str) -> None:
    alana, conversation, said = setting(db_url)

    async def scenario() -> None:
        async with world(db_url):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, code(alana))
            tools = BenchRunTools(alana.household_id, alana.person_id, bench.id, conversation, said)
            got = await tools.call(ToolCall("c1", "bench_run", {"piece_id": 1, "base_version": 1,
                                                                "language": "python"}))
            assert not got.is_error
            body = json.loads(got.content)
            assert (body["seq"], body["piece_id"], body["version"], body["outcome"], body["stdout"]) == (
                2, 1, 1, "ran", "3\n")
            assert body["files"] == {"state.txt": "1"}
            await run_piece(alana, bench.id, Run(code(alana).by, 1, 1, "python"))
            last = json.loads((await tools.call(ToolCall("c2", "bench_last_run", {"piece_id": 1}))).content)
            assert (last["by"], last["version"], last["outcome"]) == ("the person", 1, "ran")
            none = json.loads((await tools.call(ToolCall("c3", "bench_last_run", {"piece_id": 9}))).content)
            assert none == {"piece_id": 9, "run": None}

    run(scenario())


@pytest.mark.parametrize(("arguments", "starts"), [
    ({"piece_id": 2, "base_version": 1, "language": "python"}, "not_runnable:"),
    ({"piece_id": 1, "base_version": 3, "language": "python"}, "stale_base:"),
    ({"piece_id": 1, "base_version": 1, "language": "cobol"}, "cannot_run:"),
    ({"piece_id": 1, "base_version": "1", "language": "python"}, "bad_arguments:"),
    ({"piece_id": 1, "base_version": 1, "language": "python", "stdin": ""}, "bad_arguments:"),
    ({"piece_id": 1, "base_version": 1, "language": "python", "inputs": "7"}, "bad_arguments:"),
    ({"piece_id": 1, "base_version": 1, "language": "python", "inputs": [7, True]}, "bad_arguments:"),
])
def test_a_run_that_does_not_happen_is_an_error_saying_why(db_url: str, arguments: dict[str, object],
                                                           starts: str) -> None:
    alana, conversation, said = setting(db_url)

    async def scenario() -> None:
        async with world(db_url) as w:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, code(alana))
            await shop.apply(alana, bench.id, note(alana))
            tools = BenchRunTools(alana.household_id, alana.person_id, bench.id, conversation, said)
            got = await tools.call(ToolCall("c1", "bench_run", arguments))
            assert got.is_error and got.content.startswith(starts) and w.box.jobs == []

    run(scenario())


def test_a_sandbox_that_cannot_run_it_says_nothing_ran(db_url: str) -> None:
    alana, conversation, said = setting(db_url)

    async def scenario() -> None:
        async with world(db_url, Box(down=True)):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, code(alana))
            tools = BenchRunTools(alana.household_id, alana.person_id, bench.id, conversation, said)
            got = await tools.call(ToolCall("c1", "bench_run", {"piece_id": 1, "base_version": 1,
                                                                "language": "python"}))
            assert got.is_error and got.content.startswith("unavailable:")

    run(scenario())


def test_a_bench_turn_runs_code_only_on_the_bench_and_a_turn_that_landed_there_does_too(everyday: object) -> None:
    services.register(Sandbox, Box())
    try:
        assert "run_code" in names(for_turn(WEB, (20, 30)))
        for on_bench in (BENCH, replace(WEB, moved_to=4)):
            offered = names(for_turn(on_bench, (20, 30)))
            assert "run_code" not in offered and "bench_run" in offered
    finally:
        services.unregister(Sandbox)


def test_a_named_input_the_bench_cannot_give_is_an_error_naming_it_and_nothing_runs(db_url: str) -> None:
    alana, conversation, said = setting(db_url)

    async def scenario() -> None:
        async with world(db_url, Box(offered=("python", "build123d"))) as w:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, code(alana))
            tools = BenchRunTools(alana.household_id, alana.person_id, bench.id, conversation, said)
            got = await tools.call(ToolCall("c1", "bench_run", {"piece_id": 1, "base_version": 1,
                                                                "language": "build123d", "inputs": [77]}))
            assert got.is_error and got.content.startswith("bad_inputs:") and "77" in got.content
            assert w.box.jobs == []

    run(scenario())

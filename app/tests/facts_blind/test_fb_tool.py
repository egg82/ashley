"""The bench tool checks a turn she cites (design section 1): the turn is the person's, on this bench's thread, and a bad
one is refused `bad_citation` before the Workshop sees it. A choice with no citation to check goes through the tool."""

import json

from ashley.inference.model import ToolCall
from ashley.tools.bench_tools import BenchTools
from bench_blind.bb_support import Env, call, env, opened, pieces
from contract.conversations_support import run
from facts_blind_support import body_of, choice, cited


def tools(e: Env, bench_id: int) -> BenchTools:
    return BenchTools(e.world.alana.household_id, e.world.alana.person_id, bench_id)


def add(body: str) -> ToolCall:
    return call("bench_add", kind="measurements", title="facts", body=body)


def test_a_guessed_choice_row_goes_through_the_tool(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            done = await tools(e, bench).call(add(body_of(choice())))
            assert not done.is_error, done.content
            assert json.loads((await pieces(e, e.world.alana, bench))[0][2])["items"][0]["name"] == "lanyard_form"

    run(scenario())


def test_a_turn_that_is_not_on_this_benches_thread_is_bad_citation_and_nothing_is_written(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            for source in ("stated", "accepted"):
                refused = await tools(e, bench).call(add(body_of(cited(source, turn=987654321))))
                assert refused.is_error and "bad_citation" in refused.content, refused.content
            assert await pieces(e, e.world.alana, bench) == []

    run(scenario())


def test_her_stated_choice_naming_no_turn_is_refused_and_nothing_is_written(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            refused = await tools(e, bench).call(add(body_of(choice(source="stated"))))
            assert refused.is_error, refused.content
            assert await pieces(e, e.world.alana, bench) == []

    run(scenario())

"""A turn resumed by another runner stores her answer recording the person turn it answers."""

import asyncio

import psycopg
from contract.conversations_support import db_url as db_url
from contract.conversations_support import migrated_template as migrated_template
from contract.conversations_support import run
from contract.test_inflight_resume import CLAIM_S, DONE, HANG, World, database, killed, sweep, switch_on
from contract.test_inflight_resume import system as system
from contract.test_inflight_resume import world as world


def test_a_resumed_answer_records_the_person_turn_it_answers(world: World) -> None:
    world.first.inference.script = [switch_on(), HANG]
    world.second.inference.script = [DONE]

    async def go() -> None:
        async with database(world):
            await killed(world, world.first.inference.asked)
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            assert await sweep() == 1

    run(go())
    with psycopg.connect(world.url) as conn:
        rows = conn.execute("SELECT author, answers = (SELECT id FROM turns p WHERE p.author = 'person') "
                            "FROM turns ORDER BY id").fetchall()
    assert rows == [("person", None), ("ashley", True)]

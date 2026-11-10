"""An answer that outlives the outbox's `stale_s` is not lost: her turn was stored with it, and only the push is dropped,
logged `outbox.stale_dropped` with ids."""

import asyncio
from dataclasses import replace

import pytest
from ashley import logs, services
from ashley.channels.outbox import Outbox
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.channels.respond import respond
from contract.conversations_support import POLICY, events, run
from no_silent_endings_support import CHECKING, GOOD, World, database, settled


def test_a_stale_push_is_dropped_but_logged_and_the_answer_stays_on_the_thread(
        world: World, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    world.model.play(CHECKING, GOOD)
    taken: list[int] = []

    async def go() -> None:
        async with database(world) as db:
            outbox = PostgresOutbox(db, 0.2, POLICY)
            services.register(Outbox, outbox)
            try:
                await respond(replace(world.inbound(), later_by="outbox", thread="person:1:test"))
                await settled(world, 2)
                await asyncio.sleep(0.4)
                taken.extend(l.id for l in await outbox.take("person:"))
            finally:
                services.unregister(Outbox)

    run(go())
    assert taken == [] and world.queued() == 0
    assert world.hers() == [(CHECKING.text, True), (GOOD.text, False)]
    (line,) = events(capsys.readouterr().out, "outbox.stale_dropped")
    assert line["conversation"].isdigit() and int(line["age_ms"]) >= 200 and line["id"].isdigit()

"""An answer that outlives the outbox's `stale_s` is not lost: her turn was stored with it, the push is dropped (logged
`outbox.stale_dropped` with ids) and the answer is held for the asker, told once at her next reply."""

from dataclasses import replace

import pytest
from ashley import logs, services
from ashley.channels.outbox import Outbox
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.channels.respond import respond
from ashley.errands.errands import Errands
from ashley.errands.postgres import PostgresErrands
from contract.conversations_support import POLICY, events, run, scalar
from no_silent_endings_support import CHECKING, GOOD, World, database, settled


def test_a_stale_push_is_dropped_logged_and_held_for_the_asker(
        world: World, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    world.model.play(CHECKING, GOOD)
    taken: list[int] = []
    untold: list[str] = []

    async def go() -> None:
        async with database(world) as db:
            outbox = PostgresOutbox(db, 60, POLICY)
            services.register(Outbox, outbox)
            try:
                await respond(replace(world.inbound(), later_by="outbox", thread="person:1:test"))
                await settled(world, 2)
                scalar(world.url, "UPDATE outbox SET created_at = created_at - interval '2 minutes' RETURNING id")
                taken.extend(l.id for l in await outbox.take("person:"))
                errands: Errands = PostgresErrands(db)
                untold.extend(d.result for d in await errands.untold(world.who.id, 5))
                for _ in range(2):
                    await errands.told([d.id for d in await errands.untold(world.who.id, 5)])
                assert await errands.untold(world.who.id, 5) == ()
            finally:
                services.unregister(Outbox)

    run(go())
    assert taken == [] and world.queued() == 0 and untold == [GOOD.text]
    assert world.hers() == [(CHECKING.text, True), (GOOD.text, False)]
    (line,) = events(capsys.readouterr().out, "outbox.stale_dropped")
    assert line["conversation"].isdigit() and int(line["age_ms"]) >= 120_000 and line["held"] == "1" and line["id"].isdigit()

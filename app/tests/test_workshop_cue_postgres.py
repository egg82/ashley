"""Her `bench_cue` over the real Workshop: logged as hers, told to the owner's open screens as a `BenchCued` and never as
a `BenchChanged`, changing no piece's last change, refused on a piece that is not a video."""

import json

from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.inference.model import ToolCall
from ashley.live.events import BenchChanged, BenchCued
from ashley.live.live import Live
from ashley.tools.bench_tools import BenchTools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Add
from ashley.workshop.model import HER, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run
from live_support import FakeLive

URL = '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'


def test_her_cue_is_logged_told_once_to_the_owner_and_is_no_change_of_the_bench(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))
    live = FakeLive()

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        services.register(Live, live)
        services.register(Workshop, PostgresWorkshop(database, workshop_rules.load()))
        try:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "tv")
            await shop.apply(alana, bench.id, Add(HER, "video", Text("v", URL), "medium"))
            await shop.apply(alana, bench.id, Add(HER, "note", Text("n", "x"), "small"))
            before = (await shop.read(alana, bench.id)).changes
            moved = (await shop.open_benches(alana))[0].last_changed_at
            hers = BenchTools(alana.household_id, alana.person_id, bench.id)
            seek = await hers.call(ToolCall("c", "bench_cue", {"piece_id": 1, "action": "seek", "seconds": 42}))
            assert not seek.is_error and json.loads(seek.content)["piece_id"] == 1
            assert not (await hers.call(ToolCall("p", "bench_cue", {"piece_id": 1, "action": "play"}))).is_error
            cues = [e for e in live.published if isinstance(e, BenchCued)]
            assert [(c.bench_id, c.piece_id, c.action, c.seconds) for c in cues] == [(bench.id, 1, "seek", 42.0),
                                                                                    (bench.id, 1, "play", None)]
            assert all(c.shown.person_id == alana.person_id for c in cues)
            assert [e.seq for e in live.published if isinstance(e, BenchChanged)] == [1, 2]
            view = await shop.read(alana, bench.id)
            assert view.changes == before and view.undo_next == 2
            assert [(r.seq, r.by.author, r.outcome) for r in view.recent[-2:]] == [(3, "ashley", "accepted"),
                                                                                 (4, "ashley", "accepted")]
            assert (await shop.open_benches(alana))[0].last_changed_at == moved
            assert view.bench.last_changed_at == moved
            note = await hers.call(ToolCall("n", "bench_cue", {"piece_id": 2, "action": "play"}))
            assert note.is_error and note.content.startswith("not_video:")
            bad = await hers.call(ToolCall("b", "bench_cue", {"piece_id": 1, "action": "seek"}))
            assert bad.is_error and bad.content.startswith("bad_cue:")
            wrong = await hers.call(ToolCall("w", "bench_cue", {"piece_id": 1, "action": "rewind"}))
            assert wrong.is_error and wrong.content.startswith("bad_arguments:")
            assert len([e for e in live.published if isinstance(e, BenchCued)]) == 2
        finally:
            await database.close()

    run(scenario())

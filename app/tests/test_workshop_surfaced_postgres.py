"""`surface` over the real Workshop: each choice row is recorded shown once, read back from the log, shown again only
once its value changes; the record moves neither the bench's last change nor the next Undo."""

import json

from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.live.live import Live
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Add, Edit, ShownRow
from ashley.workshop.measurements import Choice
from ashley.workshop.model import HER, By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.surface import surface
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run
from live_support import FakeLive


def body(form: str) -> str:
    return json.dumps({"items": [
        {"kind": "choice", "name": "form", "label": "The lanyard", "value": form, "options": ["flat strap", "round cord"],
         "source": "guessed"},
        {"name": "width", "value": 12, "unit": "mm", "source": "guessed"}]})


def test_each_choice_is_recorded_shown_once_and_again_only_when_its_value_changes(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        services.register(Live, FakeLive())
        services.register(Workshop, PostgresWorkshop(database, workshop_rules.load()))
        try:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "lanyard clip")
            assert (await shop.apply(alana, bench.id, Add(HER, "measurements", Text("m", body("flat strap")), "small"))
                    ).outcome == "accepted"
            assert (await shop.apply(alana, bench.id, Add(HER, "note", Text("n", "x"), "small"))).outcome == "accepted"
            before = await shop.read(alana, bench.id)
            changed_at = (await shop.open_benches(alana))[0].last_changed_at
            first = await surface(alana, bench.id)
            assert [(p, r.name, r.value, r.options) for p, r in first if isinstance(r, Choice)] == [
                (1, "form", "flat strap", ("flat strap", "round cord"))]
            assert len(first) == 1
            view = await shop.read(alana, bench.id)
            assert view.surfaced == frozenset({(1, ShownRow("form", "flat strap"))})
            assert view.pieces == before.pieces and view.undo_next == before.undo_next == 2
            assert (await shop.open_benches(alana))[0].last_changed_at == changed_at
            assert await surface(alana, bench.id) == ()
            edited = await shop.apply(alana, bench.id, Edit(By(alana.person_id), 1, 1, Text("m", body("round cord"))))
            assert edited.outcome == "accepted"
            again = await surface(alana, bench.id)
            assert [(p, r.value) for p, r in again] == [(1, "round cord")]
            assert await surface(alana, bench.id) == ()
        finally:
            await database.close()

    run(scenario())

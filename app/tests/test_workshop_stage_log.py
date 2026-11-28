"""The bench's log as a screen reads it: a change of hers made in a turn carries that turn, a person's carries none."""

from ashley import services
from ashley.api.workshop_models import BenchDetail
from ashley.workshop.commands import Add
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from respond_support import ALANA, Fakes, wired as wired
from test_workshop_routes import ADD, As, command, opened
from test_workshop_routes import signed_in as signed_in


def test_a_change_of_hers_carries_the_turn_it_was_made_in_and_a_persons_carries_none(signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana).id
    assert command(alana, bench, ADD)[0] == 200
    hers = Add(By(None, turn=41), "note", Text("tray", "a tray"), "small")
    assert alana.portal is not None
    applied = alana.portal.call(services.get(Workshop).apply, Owner(ALANA.household_id, ALANA.id), bench, hers)
    assert applied.outcome == "accepted"
    detail = BenchDetail.model_validate(alana.get(f"/api/benches/{bench}").json())
    assert [(r.author, r.by_turn) for r in detail.recent] == [("person", None), ("ashley", 41)]

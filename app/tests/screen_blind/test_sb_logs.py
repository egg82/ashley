"""Contract 21: the lines a screen's commands write carry ids and counts, never a label, an entity id, a title or a
body."""

import logging

import pytest
from ashley.logs import Logfmt
from ashley.workshop.commands import Edit, Remove
from ashley.workshop.model import By, Text
from ashley.workshop.screen_controls import Control, encode
from contract.conversations_support import run
from sb_rig import HALL, PORCH, Rig
from sb_support import CLOCK, CONTROLS, add, env, fields_of, mv, put_rows
from test_sb_tools import GOOD, alana, refused, use

MARKS = ("zqLABEL", "zqTITLE", "zq_hall", "zq_porch", "zq_nowhere", "zq_night")
SEEDED_LABEL = Control("seeded", "zqLABEL-seeded", "light.turn_on", "light.zq_hall")


def lines(caplog: pytest.LogCaptureFixture, event: str) -> list[str]:
    fmt = Logfmt()
    return [out for out in (fmt.format(r) for r in caplog.records) if f"event={event} " in out + " "]


def clean(caplog: pytest.LogCaptureFixture, event: str) -> list[str]:
    found = lines(caplog, event)
    assert found, f"no {event} line: the check would pass on nothing"
    for line in found:
        assert not [m for m in MARKS if m in line], line
    return found


def test_k21_a_workshop_screen_writes_ids_and_counts_only(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    async def scenario() -> None:
        async with env(db_url) as e:
            w, me = e.world, By(e.world.alana.person_id)
            put_rows(db_url, w.tablet, w.home, SEEDED_LABEL)
            body = encode((Control("hall", "zqLABEL-hall", "light.turn_on", "light.zq_hall"),))
            await e.workshop.apply_screen(w.home, w.tablet, Edit(me, CONTROLS, 1, Text("zqTITLE-controls", body)))
            await e.workshop.apply_screen(w.home, w.tablet, Remove(me, CLOCK))
            await e.workshop.apply_screen(w.home, w.tablet, add(w.alana, "clock", "zqTITLE-clock"))
            await e.workshop.apply_screen(w.home, w.tablet, mv(w.sam, 1, 0))
            [opened] = fields_of(clean(caplog, "workshop.screen_opened"))
            assert opened["device"] == str(w.tablet) and opened["seeded"] == "4" and "bench" in opened
            commands = fields_of(clean(caplog, "workshop.command"))
            assert {c["device"] for c in commands if int(c["seq"]) > 4} == {str(w.tablet)}

    run(scenario())


def test_k21_her_tools_and_the_devices_room_write_no_label_or_entity(app: Rig, caplog: pytest.LogCaptureFixture) -> None:
    device, _ = app.tablet()
    caplog.set_level(logging.INFO)
    marked = {**GOOD, "label": "zqLABEL"}
    assert not use(app, alana(app), "screen_buttons", device_id=device, piece_id=CONTROLS, base_version=1,
                   buttons=[marked]).is_error
    refused(use(app, alana(app), "screen_buttons", device_id=device, piece_id=CONTROLS, base_version=2,
                buttons=[{**marked, "entity_id": "light.zq_nowhere"}]), "unknown_entity")
    assert app.put_controls(device, 2, {**PORCH, "entity_id": "light.zq_nowhere"}).status_code == 422
    assert app.put_controls(device, 2, {**HALL, "label": "zqLABEL"}).status_code == 200
    for event in ("tools.call", "device_controls.refused", "workshop.command"):
        clean(caplog, event)

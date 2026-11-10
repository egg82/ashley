"""Her screen tools on a real database: who they reach, what each does through the Workshop's Commands, how a refusal
reads, and that the log lines carry ids only."""

import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import pytest
from ashley import services
from ashley.channels import screen_tools
from ashley.channels.devices import Devices
from ashley.channels.model import Device, DiscordServer, Form, Listed, Satellite
from ashley.channels.screen_tools import ScreenTools
from ashley.inference.model import ToolCall
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template, run
from screen_bench_support import device, household, legacy_controls, person, shop

HOUSE = {"light.zq_hall": "light", "light.zq_bedroom": "light", "scene.zq_night": "scene"}


class Roster(Devices):
    def __init__(self, household_id: int, *listed: tuple[int, Form]) -> None:
        self._rows = [Listed(Device(i, household_id, f"tablet {i}", "hallway", "present", "text", "chat"), form)
                      for i, form in listed]

    async def by_token(self, token: str) -> Device | None:
        return None

    async def allow(self, device_id: int) -> bool:
        return True

    async def satellites(self) -> list[Satellite]:
        return []

    async def discord_servers(self) -> list[DiscordServer]:
        return []

    async def of_household(self, household_id: int) -> list[Listed]:
        return self._rows


async def fake_domains(household_id: int, person_id: int) -> dict[str, str]:
    return HOUSE


def call(name: str, **arguments: object) -> ToolCall:
    return ToolCall(f"c-{name}", name, arguments)


def with_screens(url: str, *forms: Form) -> tuple[int, tuple[int, ...]]:
    home = household(url)
    ids = tuple(device(url, home, f"d{n}") for n, _ in enumerate(forms))
    services.register(Devices, Roster(home, *zip(ids, forms, strict=True)))
    return home, ids


def scenario_of(url: str, body: Callable[[Any], Coroutine[Any, Any, None]]) -> None:
    async def scenario() -> None:
        async with shop(url) as (workshop, live):
            services.register(Workshop, workshop)
            await body(live)

    run(scenario())


def test_the_tools_reach_every_screen_for_a_known_speaker_and_the_threads_own_for_none(db_url: str,
                                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    home, (tablet, other, satellite) = with_screens(db_url, "other", "other", "satellite")
    me = person(db_url, home)

    async def body(_: object) -> None:
        for tools, reach in ((ScreenTools(home, me, None), 2), (ScreenTools(home, None, tablet), 1),
                             (ScreenTools(home, None, satellite), 0), (ScreenTools(home, None, None), 0)):
            assert len((await tools.catalogue()).specs) == (6 if reach else 0)
        listed = json.loads((await ScreenTools(home, me, None).call(call("screen_read"))).content)
        assert [s["device_id"] for s in listed["screens"]] == [tablet, other]
        one = await ScreenTools(home, None, tablet).call(call("screen_read"))
        assert [p["kind"] for p in json.loads(one.content)["pieces"]] == ["clock", "home", "controls", "conversation"]
        for wrong in (other, satellite, 999):
            refused = await ScreenTools(home, None, tablet).call(call("screen_read", device_id=wrong))
            assert refused.is_error and refused.content.startswith("no_such_screen")

    scenario_of(db_url, body)


def test_she_moves_resizes_removes_adds_and_undoes_and_the_log_says_who(db_url: str) -> None:
    home, (tablet,) = with_screens(db_url, "other")

    async def body(live: Any) -> None:
        tools = ScreenTools(home, None, tablet)
        moved = await tools.call(call("screen_move", piece_id=4, order=0, size="large"))
        assert not moved.is_error, moved.content
        gone = await tools.call(call("screen_remove", piece_id=1))
        assert not gone.is_error, gone.content
        read = json.loads((await tools.call(call("screen_read"))).content)
        assert [(p["kind"], p["size"], p["last_changed_by"]) for p in read["pieces"]] == [
            ("conversation", "large", "ashley"), ("home", "small", "ashley"), ("controls", "medium", "ashley")]
        assert read["kinds_addable"] == ["clock"] and read["undo_next"] == 6
        assert (await tools.call(call("screen_add", kind="clock", size="small"))).is_error is False
        again = await tools.call(call("screen_add", kind="clock", size="small"))
        assert again.is_error and again.content.startswith("already_shown")
        assert (await tools.call(call("screen_undo"))).is_error is False
        back = json.loads((await tools.call(call("screen_read"))).content)
        assert [p["kind"] for p in back["pieces"]] == ["conversation", "home", "controls"]
        assert len(live.published) == 4

    scenario_of(db_url, body)


def test_the_conversation_cannot_be_removed_and_an_empty_screen_has_nothing_to_undo(db_url: str) -> None:
    home, (tablet,) = with_screens(db_url, "other")

    async def body(_: object) -> None:
        tools = ScreenTools(home, None, tablet)
        refused = await tools.call(call("screen_remove", piece_id=4))
        assert refused.is_error and refused.content.startswith("required")
        read = json.loads((await tools.call(call("screen_read"))).content)
        assert read["laid_out"] is True and read["undo_next"] is None
        nothing = await tools.call(call("screen_undo"))
        assert nothing.is_error and nothing.content.startswith("nothing_to_undo")

    scenario_of(db_url, body)


def test_buttons_are_checked_against_the_house_and_stored_as_an_edit_of_the_pieces_version(
        db_url: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(screen_tools, "domains", fake_domains)
    caplog.set_level(logging.INFO)
    home, (tablet,) = with_screens(db_url, "other")
    me = person(db_url, home)
    hall = {"label": "Zq Hall lamp", "action": "light.turn_on", "entity_id": "light.zq_hall"}

    async def body(_: object) -> None:
        tools = ScreenTools(home, me, tablet)
        saved = await tools.call(call("screen_buttons", piece_id=3, base_version=1, buttons=[hall]))
        assert not saved.is_error, saved.content
        read = json.loads((await tools.call(call("screen_read"))).content)
        controls = next(p for p in read["pieces"] if p["kind"] == "controls")
        assert controls["version"] == 2 and [b["id"] for b in controls["buttons"]] == ["zq-hall-lamp"]
        stale = await tools.call(call("screen_buttons", piece_id=3, base_version=1, buttons=[hall]))
        assert stale.is_error and stale.content.startswith("stale_base")
        for bad, outcome in (({**hall, "entity_id": "light.zq_nowhere"}, "unknown_entity"),
                             ({**hall, "entity_id": "scene.zq_night"}, "unknown_entity"),
                             ({**hall, "label": "x" * 41}, "bad_label")):
            refused = await tools.call(call("screen_buttons", piece_id=3, base_version=2, buttons=[bad]))
            assert refused.is_error and refused.content.startswith(outcome), refused.content
        wrong_piece = await tools.call(call("screen_buttons", piece_id=1, base_version=1, buttons=[]))
        assert wrong_piece.is_error and wrong_piece.content.startswith("bad_arguments")
        nobody = await ScreenTools(home, None, tablet).call(call("screen_buttons", piece_id=3, base_version=2,
                                                                 buttons=[hall]))
        assert nobody.is_error and nobody.content.startswith("needs_speaker")

    scenario_of(db_url, body)
    said = " ".join(str(getattr(r, "fields", "")) + r.getMessage() for r in caplog.records)
    assert "tools.call" in said and "workshop.command" in said
    assert "Zq Hall" not in said and "light.zq_hall" not in said


def test_the_first_change_moves_the_devices_old_buttons_into_the_piece_she_reads(db_url: str) -> None:
    home, (tablet,) = with_screens(db_url, "other")
    legacy_controls(db_url, home, tablet, ("bedroom-off", "Bedroom off", "light.turn_off", "light.zq_bedroom"))

    async def body(_: object) -> None:
        tools = ScreenTools(home, None, tablet)
        before = json.loads((await tools.call(call("screen_read"))).content)
        assert before["laid_out"] is False
        await tools.call(call("screen_move", piece_id=1, order=3, size="small"))
        after = json.loads((await tools.call(call("screen_read"))).content)
        controls = next(p for p in after["pieces"] if p["kind"] == "controls")
        assert [b["id"] for b in controls["buttons"]] == ["bedroom-off"]

    scenario_of(db_url, body)


def test_a_call_with_an_argument_the_tool_lacks_or_a_bad_one_changes_nothing(db_url: str) -> None:
    home, (tablet,) = with_screens(db_url, "other")

    async def body(live: Any) -> None:
        tools = ScreenTools(home, None, tablet)
        for bad in (call("screen_move", piece_id=1, order=0, size="huge"), call("screen_add", kind="clock", size="small", extra=1),
                    call("screen_remove", piece_id="one"), call("screen_nothing")):
            result = await tools.call(bad)
            assert result.is_error
        assert not live.published

    scenario_of(db_url, body)

"""House changes by tier in a tainted turn: tier b runs, tier c is judged and the Null judge asks, so it is held; an
untainted turn runs everything; an entity named in `consequential_entities` is judged whatever its domain's tier."""

import pytest
from ashley.tools.outside import Outside
from receipts_shown import held_text
from house_double_support import MemoryHouse
from taint_tiers_blind_support import (held_tools, scenario, taint_the_turn, Tiered)
from taint_tiers_blind_house_support import do, house_tools, performed, the_house

TIER_B = [("light.turn_on", "light.porch", None), ("fan.turn_on", "fan.den", None),
          ("media_player.volume_set", "media_player.tv", None), ("scene.turn_on", "scene.movie", None),
          ("climate.set_temperature", "climate.den", None), ("input_boolean.turn_on", "input_boolean.guest", None),
          ("timer.start", "timer.tea", None), ("vacuum.start", "vacuum.robot", None),
          ("todo.add_item", "todo.inbox", {"item": "milk"}), ("todo.update_item", "todo.inbox", {"item": "milk"}),
          ("cover.open_cover", "cover.blinds", None), ("switch.turn_on", "switch.lamp", None)]
TIER_C = [("lock.unlock", "lock.front", None), ("lock.lock", "lock.front", None),
          ("cover.open_cover", "cover.garage", None), ("script.turn_on", "script.goodnight", None),
          ("alarm_control_panel.alarm_disarm", "alarm_control_panel.home", None),
          ("siren.turn_on", "siren.hall", None), ("button.press", "button.bell", None),
          ("notify.send_message", "notify.phone", None), ("automation.trigger", "automation.arrive", None),
          ("homeassistant.turn_off", "homeassistant.x", None), ("switch.turn_on", "switch.plug", None),
          ("mystery.do_it", "mystery.thing", None)]


def stack(t: Tiered, tainted: str | None, consequential: tuple[str, ...] = ()) -> tuple[Outside, MemoryHouse]:
    house = the_house()
    return taint_the_turn(house_tools(house, consequential), t.w, tainted), house


@pytest.mark.parametrize(("action", "entity", "data"), [*TIER_B, *TIER_C])
def test_an_untainted_turn_runs_every_tier(db_url: str, action: str, entity: str, data: dict[str, object] | None) -> None:
    async def body(t: Tiered) -> None:
        o, house = stack(t, None)
        got = await o.call(do(action, entity, data))
        assert not got.is_error, got.content
        assert performed(house) == [action] and await t.w.held() == []

    scenario(db_url, body)


@pytest.mark.parametrize(("action", "entity", "data"), TIER_B)
def test_a_tainted_turn_runs_a_tier_b_change(db_url: str, action: str, entity: str, data: dict[str, object] | None) -> None:
    async def body(t: Tiered) -> None:
        o, house = stack(t, "look_up")
        got = await o.call(do(action, entity, data))
        assert not got.is_error and "held" not in got.content, got.content
        assert performed(house) == [action] and await t.w.held() == []

    scenario(db_url, body)


@pytest.mark.parametrize(("action", "entity", "data"), TIER_C)
def test_a_tainted_turn_holds_a_tier_c_change_because_the_null_judge_asks(
        db_url: str, action: str, entity: str, data: dict[str, object] | None) -> None:
    async def body(t: Tiered) -> None:
        o, house = stack(t, "look_up")
        got = await o.call(do(action, entity, data))
        assert "held" in got.content and performed(house) == []
        assert held_tools(await t.w.held()) == ["house_do"]
        receipts = await o.receipts()
        assert receipts is not None and action in held_text(receipts)

    scenario(db_url, body)


def test_the_tier_follows_the_action_and_the_target_not_the_tool_name(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        o, house = stack(t, "look_up")
        await o.call(do("light.turn_on", "light.porch"))
        await o.call(do("lock.unlock", "lock.front"))
        await o.call(do("cover.open_cover", "cover.blinds"))
        await o.call(do("cover.open_cover", "cover.garage"))
        assert performed(house) == ["light.turn_on", "cover.open_cover"]
        assert [dict(arguments)["ids"] for _, arguments in await t.w.held()] == [["lock.front"], ["cover.garage"]]

    scenario(db_url, body)


@pytest.mark.parametrize("entity", ["switch.garage_relay", "light.porch"])
def test_an_entity_named_consequential_is_judged_even_when_its_domain_is_tier_b(db_url: str, entity: str) -> None:
    async def body(t: Tiered) -> None:
        action = entity.split(".")[0] + ".turn_on"
        plain, house = stack(t, "look_up")
        await plain.call(do(action, entity))
        assert performed(house) == [action], "control: without the entity listed it runs"
        o, listed = stack(t, "look_up", (entity,))
        got = await o.call(do(action, entity))
        assert "held" in got.content and performed(listed) == []

    scenario(db_url, body)


def test_a_consequential_entity_still_runs_in_an_untainted_turn(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        o, house = stack(t, None, ("switch.garage_relay",))
        await o.call(do("switch.turn_on", "switch.garage_relay"))
        assert performed(house) == ["switch.turn_on"]

    scenario(db_url, body)

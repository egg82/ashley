"""`outside.tier` and `outside.judged` carry the tool, the tier, the decision and a reason from the enum, and never
argument text, the judge's explanation or a result."""

import logging

import pytest
from taint_tiers_blind_support import (events, PLANT, REASONS, scenario, taint_the_turn, TIER_B, Tiered)
from taint_tiers_blind_house_support import do, house_tools, the_house


def test_a_tier_b_change_logs_outside_tier_with_its_tool_and_tier(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def body(t: Tiered) -> None:
        caplog.set_level(logging.INFO)
        o = taint_the_turn(house_tools(the_house()), t.w, "look_up")
        await o.call(do("todo.add_item", "todo.inbox", {"item": PLANT}))
        [line] = events(caplog, "outside.tier")
        assert (line["tool"], line["tier"]) == ("house_do", TIER_B)
        assert PLANT not in repr([r.__dict__ for r in caplog.records])

    scenario(db_url, body)


def test_a_tier_c_change_logs_outside_judged_with_decision_ask_and_a_reason_from_the_enum(
        db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def body(t: Tiered) -> None:
        caplog.set_level(logging.INFO)
        o = taint_the_turn(house_tools(the_house()), t.w, "look_up")
        await o.call(do("lock.unlock", "lock.front", {"code": PLANT}))
        [line] = events(caplog, "outside.judged")
        assert line["tool"] == "house_do" and line["decision"] == "ask" and line["reason"] in REASONS
        assert "explanation" not in line and PLANT not in repr([r.__dict__ for r in caplog.records])

    scenario(db_url, body)


def test_an_untainted_turn_logs_neither(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def body(t: Tiered) -> None:
        caplog.set_level(logging.INFO)
        o = taint_the_turn(house_tools(the_house()), t.w, None)
        await o.call(do("lock.unlock", "lock.front"))
        await o.call(do("light.turn_on", "light.porch"))
        assert events(caplog, "outside.tier") == [] and events(caplog, "outside.judged") == []

    scenario(db_url, body)

"""Whether she may make a remark nobody asked for, and whether it goes out (`ashley.initiative.remark`,
`Initiative.remark`, `Initiative.remark_speaks`, `ashley.channels.unprompted.speaks` on a turn carrying
`Inbound.remark`): the seeded roll, the facts that keep her out (unknown, night, typing, the day's cap), the line she
already sent, and the rates loader's refusals. Each case changes one fact from an allowed chance."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from ashley import services
from ashley.channels import to_phone, unprompted
from ashley.channels.checkpoint import dumps, loads
from ashley.channels.model import Inbound
from ashley.channels.push.subscriptions import Browser, Subscriptions
from ashley.inference.reply import Reply
from ashley.initiative.initiative import Initiative, NullInitiative, Scored
from ashley.initiative.remark import FILE, RATES, Chance, Rates, fingerprint, load, rolls, verdict
from ashley.initiative.weights import parse
from ashley.people.model import Person
from initiative_support import weights
from push_support import FakeSubscriptions
from inflight_blind.ifb_checkpoint_support import checkpoint

ALWAYS = Rates(chance=1.0, per_day=2, typing_within_s=900.0, repeat_within_days=30)
NEVER = replace(ALWAYS, chance=0.0)
NIGHT = parse(weights(night={"weight": 0.0, "from_hour": 22, "to_hour": 7}))
FREE = Chance("discord:1", hour=12, sent=0, since_typed_s=None, typing_known=True)
LINE = "Bold of you to call that a salad."
PERSON = Person(5, 1, "Alana")
SAID = Reply(spoken=LINE, text=LINE, says="reply")


def test_an_allowed_chance_is_allowed() -> None:
    assert verdict(FREE, ALWAYS, NIGHT) == "allowed"


def test_a_roll_that_misses_the_chance_keeps_her_out_whatever_the_facts() -> None:
    assert verdict(FREE, NEVER, NIGHT) == "rolled_out"
    assert not rolls(FREE.seed, NEVER) and rolls(FREE.seed, ALWAYS)


def test_the_roll_is_fixed_by_the_seed_and_lands_inside_the_chance_at_its_rate() -> None:
    half = replace(ALWAYS, chance=0.5)
    seeds = [f"discord:{i}" for i in range(4000)]
    first = [rolls(s, half) for s in seeds]
    assert first == [rolls(s, half) for s in seeds], "a seed rolls the same every time"
    tenth = sum(rolls(s, replace(ALWAYS, chance=0.1)) for s in seeds) / len(seeds)
    assert 0.08 < tenth < 0.12
    assert 0.47 < sum(first) / len(seeds) < 0.53


def test_the_cap_is_reached_at_per_day_remarks_and_not_before() -> None:
    assert verdict(replace(FREE, sent=1), ALWAYS, NIGHT) == "allowed"
    assert verdict(replace(FREE, sent=2), ALWAYS, NIGHT) == "capped"
    assert verdict(replace(FREE, sent=9), ALWAYS, NIGHT) == "capped"
    assert verdict(replace(FREE, sent=0), replace(ALWAYS, per_day=0), NIGHT) == "capped"


@pytest.mark.parametrize("unknown", [{"hour": None}, {"sent": None}, {"typing_known": False}])
def test_a_fact_that_could_not_be_read_keeps_her_out(unknown: dict[str, Any]) -> None:
    assert verdict(replace(FREE, **unknown), ALWAYS, NIGHT) == "unknown"


def test_the_households_night_hours_keep_her_out_across_midnight() -> None:
    got = [verdict(replace(FREE, hour=h), ALWAYS, NIGHT) for h in (21, 22, 23, 0, 6, 7)]
    assert got == ["allowed", "night", "night", "night", "night", "allowed"]


def test_typing_into_a_session_within_the_span_is_focus_and_older_typing_is_not() -> None:
    assert verdict(replace(FREE, since_typed_s=10.0), ALWAYS, NIGHT) == "typing"
    assert verdict(replace(FREE, since_typed_s=899.0), ALWAYS, NIGHT) == "typing"
    assert verdict(replace(FREE, since_typed_s=900.0), ALWAYS, NIGHT) == "allowed"


def test_night_and_focus_are_named_before_the_cap() -> None:
    assert verdict(replace(FREE, sent=5, since_typed_s=1.0), ALWAYS, NIGHT) == "typing"
    assert verdict(replace(FREE, sent=5, hour=23), ALWAYS, NIGHT) == "night"


def test_a_line_she_already_sent_is_refused_ignoring_case_punctuation_and_spacing() -> None:
    scored = Scored(NIGHT, ALWAYS)
    before = replace(FREE, said=(fingerprint("bold of you,   to call THAT a salad!"),))
    assert scored.remark_speaks(SAID, LINE, FREE)
    assert not scored.remark_speaks(SAID, LINE, before)
    assert scored.remark_speaks(SAID, "Bold of you to call that soup.", before)


def test_a_remark_goes_out_only_when_she_says_it_is_worth_saying_and_the_chance_is_allowed() -> None:
    scored = Scored(NIGHT, ALWAYS)
    assert not scored.remark_speaks(SAID.model_copy(update={"says": "none"}), LINE, FREE)
    assert not scored.remark_speaks(SAID, LINE, replace(FREE, sent=2))
    assert not Scored(NIGHT, NEVER).remark_speaks(SAID, LINE, FREE)


def test_an_unwired_initiative_never_rolls_or_lets_a_remark_out() -> None:
    null = NullInitiative()
    assert not null.rolls("discord:1") and null.remark(FREE) != "allowed"
    assert not null.remark_speaks(SAID, LINE, FREE)


def _turn(chance: Chance) -> Inbound:
    return Inbound(household_id=1, thread="discord:5", text="lunch is a salad", kind="chat", medium="text",
                   audience="household", speaker_id=5, shared=False, place=None, channel="discord", later=True,
                   source="discord:1", unprompted=True, tools_only=(), taint=None, remark=chance)


def test_the_turn_loop_lets_a_remark_out_by_its_chance_and_refuses_a_repeated_line() -> None:
    services.register(Initiative, Scored(NIGHT, ALWAYS))
    try:
        assert unprompted.speaks(SAID, _turn(FREE))
        assert unprompted.says(SAID, _turn(FREE)) == "reply"
        repeated = _turn(replace(FREE, said=(fingerprint(LINE),)))
        assert not unprompted.speaks(SAID, repeated)
        assert unprompted.as_said(SAID, repeated).text != LINE
    finally:
        services.unregister(Initiative)


def test_the_shipped_rates_load_and_keep_remarks_at_least_a_day() -> None:
    assert load(FILE) == RATES
    assert 0.0 < RATES.chance <= 1.0 and RATES.per_day >= 1
    assert replace(RATES, repeat_within_days=1).keep_s == 86400.0


@pytest.mark.parametrize("change", [
    {"chance": 1.5}, {"chance": -0.1}, {"chance": True}, {"per_day": -1}, {"per_day": 1.5},
    {"typing_within_s": 0}, {"repeat_within_days": 0}, {"extra": 1},
])
def test_the_loader_refuses_rates_out_of_range_or_with_unknown_keys(change: dict[str, Any], tmp_path: Path) -> None:
    raw = {"chance": 0.1, "per_day": 2, "typing_within_s": 900, "repeat_within_days": 30, **change}
    path = tmp_path / "remark.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        load(path)
    path.write_text(json.dumps({k: v for k, v in raw.items() if k != "chance"}))
    with pytest.raises(ValueError):
        load(path)


def test_a_remarks_chance_survives_the_checkpoint_so_a_resumer_decides_the_same() -> None:
    base = checkpoint()
    chance = replace(FREE, sent=1, since_typed_s=1200.5, said=(fingerprint(LINE), fingerprint("other")))
    got = loads(dumps(replace(base, inbound=replace(base.inbound, unprompted=True, remark=chance))))
    assert got.inbound.remark == chance
    assert loads(dumps(base)).inbound.remark is None


def test_a_remark_never_offers_the_speakers_phone_where_another_woken_turn_would() -> None:
    subscribed = FakeSubscriptions()
    services.register(Subscriptions, subscribed)
    try:
        asyncio.run(subscribed.add(1, 5, Browser("https://push.example/1", "k", "a")))
        woken = replace(_turn(FREE), remark=None)
        assert asyncio.run(to_phone.reachable(woken, PERSON)) == 5, "the control: a woken turn offers the phone"
        assert asyncio.run(to_phone.reachable(_turn(FREE), PERSON)) is None
    finally:
        services.unregister(Subscriptions)

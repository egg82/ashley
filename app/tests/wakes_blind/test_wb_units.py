"""The pure pieces: the wake rule's body, the wake action in an automation, `Only`, Initiative, the unprompted reply,
and the tools a turn with no speaker is offered."""

import json
from typing import Any

import pytest
from ashley import services
from ashley.channels import unprompted
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import for_turn, sources
from ashley.connections.connections import Connections
from ashley.initiative.initiative import Initiative, NullInitiative, Scored
from ashley.initiative.weights import WEIGHTS
from ashley.inference.model import ToolCall
from ashley.inference.reply import Reply
from ashley.tools.only import Only
from ashley.tools.tools import Tools
from ashley.workshop import wake_action, wake_rule
from ashley.workshop.automation_config import well_formed as automation_well_formed
from contract.conversations_support import run
from money_support import HeldConnections
from wb_runner_support import ALLOWED, House

# ---- the rule's body

def body(**changes: object) -> str:
    return json.dumps({"event": "arrived", "brief": "Greet them.", "tools": ["lamp_on"], **changes})


@pytest.fixture
def catalogue() -> None:
    services.register(Tools, House())


def test_a_rule_is_read_back_as_written(catalogue: None) -> None:
    assert wake_rule.rule_of(body()) == wake_rule.WakeRule("arrived", "Greet them.", ("lamp_on",))
    assert wake_rule.well_formed(body()) is True


def test_an_empty_body_is_a_draft_that_passes_and_is_no_rule() -> None:
    assert wake_rule.well_formed("") is True and wake_rule.rule_of("") is None


def test_no_tools_is_a_rule() -> None:
    assert wake_rule.rule_of(body(tools=[])) == wake_rule.WakeRule("arrived", "Greet them.", ())


BAD = {"not json": "arrived", "an array": "[]", "a string": '"arrived"', "null": "null",
       "extra key": body(extra=1), "no brief": json.dumps({"event": "arrived", "tools": []}),
       "no event": json.dumps({"brief": "x", "tools": []}), "no tools": json.dumps({"event": "arrived", "brief": "x"}),
       "event not a slug": body(event="Arrived"), "event with space": body(event="at home"),
       "event empty": body(event=""), "event long": body(event="a" * 65), "event a number": body(event=1),
       "brief a number": body(brief=3), "brief too long": body(brief="x" * (wake_rule.MAX_BRIEF + 1)),
       "brief blank": body(brief="   "), "tools repeat a name": body(tools=["lamp_on", "lamp_on"]),
       "tool name with a space": body(tools=["lamp on"]), "tool name empty": body(tools=[""]),
       "tools a string": body(tools="lamp_on"), "tools hold a number": body(tools=[1]),
       "tools hold null": body(tools=[None])}


@pytest.mark.parametrize("name", BAD)
def test_a_body_not_of_the_shape_is_refused_and_is_no_rule(catalogue: None, name: str) -> None:
    assert wake_rule.well_formed(BAD[name]) is False and wake_rule.rule_of(BAD[name]) is None


def test_a_brief_of_exactly_the_limit_passes(catalogue: None) -> None:
    assert wake_rule.well_formed(body(brief="x" * wake_rule.MAX_BRIEF)) is True


def test_a_rule_naming_a_tool_the_house_does_not_have_is_still_well_formed(catalogue: None) -> None:
    assert wake_rule.well_formed(body(tools=["lamp_on", "no_such_tool_zq"])) is True


# ---- the wake action

DATA = {"event": "arrived", "event_id": "{{ context.id }}"}


def action(data: dict[str, Any], key: str = "action") -> dict[str, Any]:
    return {key: "rest_command.ashley_wake", "data": data}


def config(*actions: dict[str, Any]) -> dict[str, Any]:
    return {"alias": "a", "triggers": [{"trigger": "state", "entity_id": "person.alana", "to": "home"}],
            "actions": list(actions), "mode": "single"}


def test_a_wake_action_of_the_shape_passes_and_names_its_event() -> None:
    cfg = config(action({**DATA, "who": "{{ trigger.to_state.entity_id }}", "what": "front_door",
                         "when": "{{ now().isoformat() }}"}))
    assert wake_action.well_formed(cfg) is True and wake_action.events_of(cfg) == ("arrived",)


def test_a_who_may_be_a_person_entity() -> None:
    assert wake_action.well_formed(config(action({**DATA, "who": "person.alana"}))) is True


def test_an_automation_with_no_wake_action_passes_and_has_no_events() -> None:
    cfg = config({"action": "light.turn_on", "target": {"entity_id": "light.hall"}, "data": {"message": "any words"}})
    assert wake_action.well_formed(cfg) is True and wake_action.events_of(cfg) == ()


def test_events_follow_the_order_of_the_actions_nested_ones_included() -> None:
    cfg = config(action({**DATA, "event": "left"}),
                 {"choose": [{"conditions": [], "sequence": [action({**DATA, "event": "arrived"})]}],
                  "default": [{"if": [], "then": [action({**DATA, "event": "late"})]}]})
    assert wake_action.events_of(cfg) == ("left", "arrived", "late")


WRONG: dict[str, dict[str, Any]] = {
    "free text field": {**DATA, "message": "tell her something"},
    "no event_id": {"event": "arrived"},
    "no event": {"event_id": "{{ context.id }}"},
    "event_id literal that is not context.id template": {**DATA, "event_id": "fixed-id"},
    "event not a slug": {**DATA, "event": "Arrived Home"},
    "event is words around a template": {**DATA, "event": "x {{ a }} y"},
    "who is free text": {**DATA, "who": "Alana came home"},
    "who is a light": {**DATA, "who": "light.hall"},
    "what is a sentence": {**DATA, "what": "the front door opened"},
    "when is words around a template": {**DATA, "when": "at {{ now() }} today"},
    "two templates": {**DATA, "who": "{{ a }}{{ b }}"},
}


@pytest.mark.parametrize("name", WRONG)
def test_a_wake_action_off_the_shape_is_refused(name: str) -> None:
    assert wake_action.well_formed(config(action(WRONG[name]))) is False


@pytest.mark.parametrize("extra", [{"target": {"entity_id": "light.hall"}}, {"alias": "x"}, {"enabled": False}, {"service": "x"}])
def test_a_wake_action_with_keys_beyond_action_and_data_is_refused(extra: dict[str, Any]) -> None:
    assert wake_action.well_formed(config({**action(DATA), **extra})) is False


def test_a_wake_action_without_data_is_refused() -> None:
    assert wake_action.well_formed(config({"action": "rest_command.ashley_wake"})) is False


def test_a_bad_wake_action_nested_deep_is_still_refused() -> None:
    nested = config({"choose": [{"conditions": [], "sequence": [action({**DATA, "message": "words"})]}]})
    assert wake_action.well_formed(nested) is False


def test_the_automation_piece_check_refuses_a_bad_wake_action() -> None:
    assert automation_well_formed(json.dumps(config(action({**DATA, "message": "words"})))) is False
    assert automation_well_formed(json.dumps(config(action(DATA)))) is True


def test_the_legacy_service_key_is_checked_like_the_action_key() -> None:
    cfg = config(action({**DATA, "message": "words"}, key="service"))
    assert wake_action.well_formed(cfg) is False
    assert automation_well_formed(json.dumps(cfg)) is False


# ---- Only

def test_a_name_the_source_does_not_offer_is_not_offered_and_the_known_ones_are() -> None:
    only = Only(House(), ("lamp_on", "no_such_tool_zq"))

    async def go() -> None:
        assert [t.name for t in (await only.catalogue()).specs] == [ALLOWED.name]

    run(go())


def test_only_lists_and_calls_the_named_tools() -> None:
    only = Only(House(), ("lamp_on",))

    async def go() -> None:
        assert [t.name for t in (await only.catalogue()).specs] == [ALLOWED.name]
        assert (await only.call(ToolCall("c", "lamp_on", {}))).is_error is False
        denied = await only.call(ToolCall("d", "garage_open", {}))
        assert denied.is_error and denied.call_id == "d"

    run(go())


def test_only_never_reaches_a_tool_not_named() -> None:
    source = House()
    only = Only(source, ("lamp_on",))

    async def go() -> None:
        await only.call(ToolCall("d", "garage_open", {}))
        await only.call(ToolCall("e", "nothing", {}))

    run(go())
    assert source.ran == []


def test_only_with_no_names_offers_and_runs_nothing() -> None:
    source = House()
    only = Only(source, ())

    async def go() -> None:
        assert (await only.catalogue()).specs == ()
        assert (await only.call(ToolCall("d", "lamp_on", {}))).is_error

    run(go())
    assert source.ran == []


def test_only_matches_an_entry_after_a_domain_prefix_and_not_a_suffix_of_a_word() -> None:
    from ashley.tools.tools import Catalogue
    from ashley.inference.model import ToolResult, ToolSpec

    class Prefixed(Tools):
        async def catalogue(self) -> Catalogue:
            return Catalogue((ToolSpec("light__turn_on", "x", {"type": "object"}, reads=False),
                              ToolSpec("lamp_turn_on", "x", {"type": "object"}, reads=False)), "")

        async def call(self, call: ToolCall) -> ToolResult:
            return ToolResult(call.id, "{}")

    async def go() -> None:
        got = await Only(Prefixed(), ("turn_on",)).catalogue()
        assert [t.name for t in got.specs] == ["light__turn_on"]

    run(go())


# ---- Initiative and the unprompted reply

WORTH = Reply(spoken="Hi.", text="Hi.", says="reply")
NOT_WORTH = Reply(spoken="Hi.", text="Hi.", says="none")
SCORED = Scored(WEIGHTS)


def test_worth_saying_is_the_replys_own_field_and_pure() -> None:
    assert SCORED.speaks(WORTH, None, False) is True and SCORED.speaks(NOT_WORTH, None, False) is False
    assert [SCORED.speaks(NOT_WORTH, None, False) for _ in range(3)] == [False] * 3


def test_a_reply_defaults_to_worth_saying() -> None:
    assert Reply(spoken="a", text="a").says == "reply"


def test_the_words_never_decide_it() -> None:
    quiet = Reply(spoken="I have nothing to say.", text="", says="reply")
    loud = Reply(spoken="", text="", says="none")
    assert SCORED.speaks(quiet, None, False) is True and SCORED.speaks(loud, None, False) is False


def test_the_unwired_initiative_never_speaks() -> None:
    assert NullInitiative().speaks(WORTH, None, False) is False and Initiative.null().speaks(WORTH, None, False) is False


def inbound(**changes: Any) -> Inbound:
    base: dict[str, Any] = dict(household_id=10, thread="phone:1", text="m", kind="chat", medium="text", audience="owner",
                                speaker_id=1, shared=False, place=None, channel="web")
    return Inbound(**{**base, **changes})


def test_a_reply_to_a_person_always_goes_out_whatever_initiative_says() -> None:
    services.register(Initiative, NullInitiative())
    assert unprompted.speaks(WORTH, inbound()) is True and unprompted.speaks(NOT_WORTH, inbound()) is True


@pytest.mark.parametrize("policy,reply,goes", [(SCORED, WORTH, True), (SCORED, NOT_WORTH, False),
                                              (NullInitiative(), WORTH, False)])
def test_an_unprompted_reply_goes_out_as_initiative_decides(policy: Initiative, reply: Reply, goes: bool) -> None:
    services.register(Initiative, policy)
    assert unprompted.speaks(reply, inbound(unprompted=True)) is goes


def test_a_reply_that_goes_out_is_recorded_unchanged_and_one_that_does_not_is_quiet_in_every_field() -> None:
    services.register(Initiative, SCORED)
    assert unprompted.as_said(WORTH, inbound(unprompted=True)) == WORTH
    quiet = unprompted.as_said(NOT_WORTH, inbound(unprompted=True))
    assert quiet.spoken == unprompted.QUIET and quiet.text == unprompted.QUIET
    assert NOT_WORTH.text not in (quiet.spoken, quiet.text)
    assert unprompted.as_said(NOT_WORTH, inbound()) == NOT_WORTH


# ---- the tools of a turn nobody asked for

def money_offered(inbound_: Inbound) -> bool:
    held = HeldConnections()
    held.connect(inbound_.household_id)
    services.register(Connections, held)
    return "money" in sources(inbound_)


def test_the_probe_can_see_money_when_one_person_is_alone_with_her() -> None:
    assert money_offered(inbound(speaker_id=1)) is True


def test_a_turn_with_no_speaker_is_never_offered_the_owner_alone_tools() -> None:
    owner_alone_shape = dict(audience="owner", shared=False, speaker_id=None, channel="web")
    assert money_offered(inbound(unprompted=True, **owner_alone_shape)) is False
    assert money_offered(inbound(unprompted=True, tools_only=("lamp_on",), **owner_alone_shape)) is False


def test_tools_only_narrows_what_a_turn_offers_to_the_names() -> None:
    services.register(Tools, House())

    async def go() -> None:
        got = await for_turn(inbound(unprompted=True, tools_only=("lamp_on",))).catalogue()
        assert [t.name for t in got.specs] == ["lamp_on"]
        none = await for_turn(inbound(unprompted=True, tools_only=())).catalogue()
        assert none.specs == ()
        every = await for_turn(inbound()).catalogue()
        assert {t.name for t in every.specs} >= {"lamp_on", "garage_open"}

    run(go())


def test_tools_only_narrows_even_the_tools_a_speaker_would_add() -> None:
    held = HeldConnections()
    held.connect(10)
    services.register(Connections, held)
    services.register(Tools, House())

    async def go() -> None:
        got = await for_turn(inbound(unprompted=True, tools_only=("lamp_on",))).catalogue()
        assert [t.name for t in got.specs] == ["lamp_on"]

    run(go())

"""Which turns may escalate: only a kind whose `turns.json` entry says `"escalates": true` (chat), on a channel that takes
replies said after the response; and what the escalated turn runs under."""

import json
from dataclasses import replace
from importlib import resources

import pytest
from ashley.channels import escalation, limits
from ashley.channels.landing import Landing
from ashley.channels.limits import KINDS, Limits
from ashley.channels.model import Inbound
from ashley.conversations.model import Kind

LOADED = limits.load()


def flags() -> dict[str, object]:
    data = json.loads(resources.files("ashley.channels").joinpath("turns.json").read_text())
    return {kind: entry.get("escalates", False) for kind, entry in data.items()}


def test_the_shipped_flags_name_chat_alone() -> None:
    assert flags() == {"command": False, "chat": True, "brainstorm": False}
    assert [kind for kind in KINDS if LOADED[kind].escalates] == ["chat"]


@pytest.mark.parametrize("kind", KINDS)
def test_a_kind_escalates_exactly_when_its_limits_say_so(kind: Kind) -> None:
    assert (escalation.of(kind, LOADED) is not None) == LOADED[kind].escalates


@pytest.mark.parametrize("kind", ["command", "brainstorm"])
def test_command_and_bench_turns_have_no_escalation(kind: Kind) -> None:
    assert escalation.of(kind, LOADED) is None


def test_a_limits_entry_without_the_flag_does_not_escalate() -> None:
    assert Limits(6, 1000, 5, 0).escalates is False
    assert escalation.of("chat", {**LOADED, "chat": replace(LOADED["chat"], escalates=False)}) is None


def test_chat_escalates_to_the_escalated_task_under_brainstorms_limits_with_its_own_reply_length() -> None:
    got = escalation.of("chat", {**LOADED, "chat": replace(LOADED["chat"], reply_chars=321)})
    assert got is not None and got.task == "escalated"
    assert got.limits == replace(LOADED["brainstorm"], reply_chars=321, escalates=False)


def test_the_escalated_limits_do_not_escalate_again() -> None:
    got = escalation.of("chat", LOADED)
    assert got is not None and not got.limits.escalates


def web(kind: Kind = "chat", later: bool = True) -> Inbound:
    return Inbound(10, "web:1", "hi", kind, "text", "owner", 1, False, None, "web", later=later, later_by="turn",
                   opens_benches=True, on_page=True)


def landing(inbound: Inbound) -> Landing:
    return Landing(inbound, (1, 2), LOADED)


def test_a_chat_turn_on_a_channel_that_takes_a_later_reply_lands_with_an_escalation() -> None:
    got = landing(web()).escalation
    assert got is not None and got.task == "escalated" and got.limits.escalates is False


def test_a_chat_turn_on_a_channel_with_no_later_reply_has_none() -> None:
    assert landing(web(later=False)).escalation is None


def test_a_command_turn_has_none_even_where_a_later_reply_is_taken() -> None:
    assert landing(web("command")).escalation is None

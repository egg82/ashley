"""`respond` and the history it carries, against the fakes: each stored turn records who could hear it (private to the
speaker on an owner-only channel or when sent to their phone, else shared); `Conversations.carried` is asked for the
speaker, alone only on an owner-only channel, with the kind's budgets and the message's words; the recent turns are the
messages, budget-capped, and the relevant ones the persona's `said_before`, each with its age; `respond.done` counts
them and what was held back, never text."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from ashley import logs
from ashley.channels import respond as respond_module
from ashley.channels.model import Audience, Inbound
from ashley.channels.push.subscriptions import Subscription
from ashley.channels.respond import respond
from ashley.conversations.model import Hearer, NewTurn, Turn
from ashley.inference.model import Message
from ashley.inference.reply import Reply
from contract.conversations_support import events
from later_support import FakeOutbox, outbox as outbox
from push_support import FakeSubscriptions, browser, subscriptions as subscriptions
from respond_support import ALANA, EPOCH, HOME, Fakes, inbound, wired as wired

REPLY = Reply(spoken="Done.", text="Done.")
MARK = "zq-history-mark"


def owner_inbound(text: str = "hello", speaker_id: int | None = ALANA.id) -> Inbound:
    return Inbound(HOME.id, "web:1", text, "chat", "text", "owner", speaker_id, False, None, "web")


def stored(fakes: Fakes) -> list[NewTurn]:
    return fakes.conversations.added


@pytest.mark.parametrize(("audience", "heard"), [("owner", ("private", ALANA.id)), ("present", ("shared", None)),
                                                 ("household", ("shared", None))])
def test_both_turns_record_who_could_hear_them(wired: Fakes, audience: Audience,
                                               heard: tuple[str, int | None]) -> None:
    wired.inference.script = [REPLY]
    asyncio.run(respond(replace(owner_inbound(), audience=audience)))
    assert [(t.author, t.heard, t.owner_id) for t in stored(wired)] == [("person", *heard), ("ashley", *heard)]


def test_an_unknown_speaker_on_an_owner_channel_is_private_to_no_one(wired: Fakes) -> None:
    wired.inference.script = [REPLY]
    asyncio.run(respond(owner_inbound(speaker_id=None)))
    assert [(t.heard, t.owner_id) for t in stored(wired)] == [("private", None), ("private", None)]


def test_her_reply_sent_to_the_phone_is_private_to_the_speaker(
        wired: Fakes, outbox: FakeOutbox, subscriptions: FakeSubscriptions) -> None:
    subscriptions.rows.append(Subscription(1, HOME.id, ALANA.id, browser(1)))
    wired.inference.script = [Reply(spoken="On your phone.", text="1. a\n2. b", to_phone=True)]
    asyncio.run(respond(inbound(medium="spoken", speaker_id=ALANA.id)))
    person, hers = stored(wired)
    assert (person.heard, person.owner_id) == ("shared", None)
    assert (hers.text, hers.heard, hers.owner_id) == ("1. a\n2. b", "private", ALANA.id)


@pytest.mark.parametrize(("audience", "owner_only"), [("owner", True), ("present", False), ("household", False)])
def test_carried_is_asked_for_the_speaker_with_the_kinds_budgets(wired: Fakes, audience: Audience,
                                                                  owner_only: bool) -> None:
    wired.inference.script = [REPLY]
    asyncio.run(respond(replace(owner_inbound("the garden gate"), audience=audience)))
    ((hearer, _, before, query, recent, relevant),) = wired.conversations.carry_calls
    limits = respond_module.LIMITS["chat"]
    assert hearer == Hearer(HOME.id, ALANA.id, owner_only)
    assert (query, recent, relevant) == ("the garden gate", limits.recent_turns, limits.relevant_turns)
    assert before == next(iter(wired.conversations.convs.values())).turns[0].id


def test_the_recent_budget_caps_the_messages(wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(respond_module.LIMITS, "command", replace(respond_module.LIMITS["command"], recent_turns=2))
    wired.inference.script = [REPLY, REPLY, REPLY]
    for text in ("one", "two", "three"):
        asyncio.run(respond(inbound(text)))
    assert wired.inference.prompts[-1].messages == (
        Message("person", "(Sat 24 Oct 2026 18:00) two"), Message("ashley", "(Sat 24 Oct 2026 18:00) Done."), Message("person", "three"))


def test_relevant_turns_reach_the_persona_with_their_age_and_the_log_counts(
        wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    wired.conversations.relevant = (Turn(5, "person", ALANA.id, f"the gate {MARK}", EPOCH - timedelta(days=3)),
                                    Turn(6, "ashley", None, f"fixed {MARK}", EPOCH - timedelta(hours=2)))
    wired.conversations.filtered = 4
    wired.inference.script = [REPLY]
    asyncio.run(respond(inbound("the gate")))
    assert wired.contexts[0].said_before == (f"(Wed 21 Oct 2026 18:00) Alana: the gate {MARK}",
                                                  f"(Sat 24 Oct 2026 16:00) You: fixed {MARK}")
    out = capsys.readouterr().out
    (done,) = events(out, "respond.done")
    assert (done["recent_turns"], done["relevant_turns"], done["turns_filtered"]) == ("0", "2", "4")
    assert MARK not in out

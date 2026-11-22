"""With no cut a turn offers every tool and every source's instructions on its first step, as before tools could be
loaded on demand: the first step's prompt is pinned by hash, so a change that alters it fails here."""

import asyncio
from collections.abc import Generator
from dataclasses import replace

import pytest
from ashley import services
from ashley.channels import cut, speaker, turn_prompt
from ashley.channels.limits import load as load_limits
from ashley.channels.landing import Landing
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.evals import prompt_sizes_live
from ashley.inference.model import Message, Prompt
from ashley.people.people import People
from ashley.senses.presence import Presence
from on_demand_support import fingerprint, offer, sources
from respond_support import ALANA, HOME, FakeConversations, FakePeople, FakePresence

PINNED = "3adcfbd8"


@pytest.fixture(autouse=True)
def seams() -> Generator[None]:
    services.register(People, FakePeople())
    services.register(Presence, FakePresence())
    services.register(Conversations, FakeConversations())
    services.register(InFlight, InFlight.null())
    cut.install(cut.NO_CUT)
    yield
    cut.install(cut.NO_CUT)
    for interface in (People, Presence, Conversations, InFlight):
        services.unregister(interface)


def first_step(monkeypatch: pytest.MonkeyPatch) -> Prompt:
    offer(monkeypatch, sources())
    ask = replace(prompt_sizes_live.inbound("chat", "web", HOME.id, ALANA.id, "hello"), tools_only=None)
    who = asyncio.run(speaker.who(ask))
    prompted = asyncio.run(turn_prompt.build(ask, who, Landing(ask, (0, 0), load_limits()), turn_prompt.nothing_carried()))
    assert prompted.catalogue is not None
    return Prompt(prompted.system, (Message("person", "hello"),), prompted.catalogue.specs, "auto")


def test_with_no_cut_the_first_step_offers_every_tool_and_every_sources_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = first_step(monkeypatch)
    assert [s.name for s in prompt.tools] == ["lights", "weather", "remind", "reminders", "mail_search", "mail_send",
                                              "money_accounts"]
    assert all(text in prompt.system["default"].stable for text in ("How the lights work.", "How money works."))
    assert fingerprint(prompt) == PINNED

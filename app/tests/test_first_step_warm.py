"""A satellite's wake warms the model her turn will ask: `first_step.warm` primes the prefix her turn's first step
sends (the tools as offered, every variant's stable system prompt), whoever the voice match later names, and a prompt
that cannot be built primes nothing and does not raise."""

import asyncio
import logging
from collections.abc import Generator

import pytest
from ashley import services
from ashley.channels import first_step
from ashley.channels.model import Inbound
from ashley.channels.respond import respond
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.inference import anthropic_wire
from ashley.inference.inference import Inference
from ashley.inference.model import Prompt, ToolSpec
from ashley.inference.reply import Reply
from ashley.people.people import People
from ashley.senses.presence import Presence
from ashley.tools.tools import Tools
from respond_support import ALANA, HOME, FakeConversations, FakeInference, FakePeople, FakePresence, FakeTools

LIGHTS = ToolSpec("lights", "the lights", {"type": "object"})
LOCK = ToolSpec("lock", "the lock", {"type": "object"})
_WIRED = (People, Presence, Conversations, InFlight, Tools, Inference)


@pytest.fixture
def turn() -> Generator[FakeInference]:
    inference = FakeInference()
    services.register(People, FakePeople())
    services.register(Presence, FakePresence())
    services.register(Conversations, FakeConversations())
    services.register(InFlight, InFlight.null())
    services.register(Tools, FakeTools((LIGHTS, LOCK)))
    services.register(Inference, inference)
    yield inference
    for interface in _WIRED:
        services.unregister(interface)


def heard(text: str, heard_as: int | None) -> Inbound:
    """What a satellite's run asks (`voice.run.Run._inbound`)."""
    return Inbound(HOME.id, "device:7", text, "command", "spoken", "present", None, True, "kitchen", "voice",
                   remembers=False, heard_as=heard_as, later=True, taint=None, overhears=True)


def prefix(prompt: Prompt) -> tuple[object, ...]:
    return ({v: anthropic_wire.system(s) for v, s in prompt.system.items()}, anthropic_wire.tools(prompt.tools))


@pytest.mark.parametrize("heard_as", [None, ALANA.id])
def test_the_wake_primes_the_prefix_her_first_step_sends(turn: FakeInference, heard_as: int | None) -> None:
    assert asyncio.run(first_step.warm(heard(".", None)))
    turn.script = [Reply(spoken="Noon.", text="Noon.")]
    asyncio.run(respond(heard("what time is it", heard_as)))
    [(task, primed, household)] = turn.primed
    assert (task, household) == ("command", HOME.id)
    assert prefix(primed) == prefix(turn.prompts[0])
    assert len(primed.tools) == len(turn.prompts[0].tools) >= 2


def test_a_prompt_that_cannot_be_built_primes_nothing(turn: FakeInference, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR, "ashley.channels")
    services.unregister(People)
    assert not asyncio.run(first_step.warm(heard(".", None)))
    assert turn.primed == []
    assert [r for r in caplog.records if "respond.warm_failed" in r.getMessage()]

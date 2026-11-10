"""Pins what a reply does with the household's overrides: the heads read for the turn's household reach
`persona.Context.overrides` as `bodies(heads)`, and a read that fails leaves the shipped persona (empty `overrides`),
logs `persona.overrides_unreachable` and does not stop the reply."""

import asyncio
from collections.abc import Generator, Mapping
from datetime import UTC, datetime

import pytest
from contract.conversations_support import events
from respond_support import HOME, Fakes, inbound
from respond_support import wired as wired

from ashley import logs, services
from ashley.channels.respond import respond
from ashley.inference.reply import Reply
from ashley.persona import persona
from ashley.skills.persona import PersonaOverrides, PersonaUnavailable, PersonaVersion

REPLY = Reply(spoken="It is on.", text="It's on.")
AT = datetime(2026, 11, 1, tzinfo=UTC)


def head(body: str | None, version: int = 1) -> PersonaVersion:
    return PersonaVersion(version, body, "w", "y", 0, None, 1, AT)


class FakeOverrides(PersonaOverrides):
    def __init__(self, answer: Mapping[str, PersonaVersion] | Exception) -> None:
        self.answer = answer
        self.asked: list[int] = []

    async def heads(self, household_id: int) -> Mapping[str, PersonaVersion]:
        self.asked.append(household_id)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    async def changelog(self, household_id: int, section: str) -> tuple[PersonaVersion, ...]:
        raise AssertionError("a reply reads the heads, not a changelog")


@pytest.fixture
def overrides() -> Generator[None]:
    yield
    services.unregister(PersonaOverrides)


@pytest.mark.usefixtures("overrides")
def test_the_turns_households_heads_become_the_contexts_overrides(wired: Fakes) -> None:
    fake = FakeOverrides({"voice": head("Blunt."), "wit": head(None, 2), "reply": head("Plain.")})
    services.register(PersonaOverrides, fake)
    wired.inference.script = [REPLY]
    asyncio.run(respond(inbound()))
    assert fake.asked == [HOME.id]
    assert dict(wired.contexts[0].overrides) == {"voice": "Blunt.", "reply": "Plain."}


@pytest.mark.usefixtures("overrides")
def test_each_reply_reads_again_nothing_is_cached(wired: Fakes) -> None:
    fake = FakeOverrides({"voice": head("Blunt.")})
    services.register(PersonaOverrides, fake)
    wired.inference.script = [REPLY, REPLY]
    asyncio.run(respond(inbound("one")))
    fake.answer = {"voice": head("Gentler.", 2)}
    asyncio.run(respond(inbound("two")))
    assert [dict(c.overrides) for c in wired.contexts] == [{"voice": "Blunt."}, {"voice": "Gentler."}]
    assert fake.asked == [HOME.id, HOME.id]


@pytest.mark.usefixtures("overrides")
def test_a_household_with_no_heads_gets_the_shipped_persona(wired: Fakes) -> None:
    services.register(PersonaOverrides, FakeOverrides({}))
    wired.inference.script = [REPLY]
    asyncio.run(respond(inbound()))
    assert dict(wired.contexts[0].overrides) == {}


@pytest.mark.usefixtures("overrides")
def test_a_failed_read_falls_back_to_the_shipped_persona_logs_it_and_still_replies(
        wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    services.register(PersonaOverrides, FakeOverrides(PersonaUnavailable("down")))
    wired.inference.script = [REPLY]
    out = asyncio.run(respond(inbound()))
    assert out.body == REPLY.text
    assert dict(wired.contexts[0].overrides) == {} and wired.contexts[0].overrides == persona.NO_OVERRIDES
    assert len(events(capsys.readouterr().out, "persona.overrides_unreachable")) == 1


def test_unwired_the_reply_uses_the_shipped_persona(wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    services.unregister(PersonaOverrides)
    wired.inference.script = [REPLY]
    out = asyncio.run(respond(inbound()))
    assert out.body == REPLY.text and dict(wired.contexts[0].overrides) == {}
    assert len(events(capsys.readouterr().out, "persona.overrides_unreachable")) <= 1

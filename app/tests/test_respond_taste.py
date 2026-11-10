"""A reply's prompt carries the household's persona overrides, read for that reply; unreadable, she uses the shipped
persona and says so in the log."""

import asyncio
from collections.abc import Generator, Mapping
from datetime import UTC, datetime

import pytest
from ashley import logs, services
from ashley.channels.respond import respond
from ashley.inference.reply import Reply
from ashley.skills.persona import PersonaOverrides, PersonaVersion
from contract.conversations_support import events
from respond_support import HOME, Fakes, inbound, wired as wired

REPLY = Reply(spoken="It is on.", text="It's on.")
AT = datetime(2026, 11, 10, tzinfo=UTC)


class FakeOverrides(PersonaOverrides):
    def __init__(self) -> None:
        self.asked: list[int] = []

    async def heads(self, household_id: int) -> Mapping[str, PersonaVersion]:
        self.asked.append(household_id)
        return {"wit": PersonaVersion(2, "Dry.", "Changed", "why", 1, None, 1, AT),
                "examples": PersonaVersion(3, None, "Back to the shipped text", "why", 2, 0, 1, AT)}

    async def changelog(self, household_id: int, section: str) -> tuple[PersonaVersion, ...]:
        return ()


@pytest.fixture
def overrides() -> Generator[FakeOverrides]:
    fake = FakeOverrides()
    services.register(PersonaOverrides, fake)
    yield fake
    services.unregister(PersonaOverrides)


def test_the_prompt_carries_each_override_in_force(wired: Fakes, overrides: FakeOverrides) -> None:
    wired.inference.script = [REPLY, REPLY]
    asyncio.run(respond(inbound()))
    asyncio.run(respond(inbound()))
    assert [dict(c.overrides) for c in wired.contexts] == [{"wit": "Dry."}, {"wit": "Dry."}]
    assert overrides.asked == [HOME.id, HOME.id]


def test_unreadable_overrides_leave_the_shipped_persona(wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    wired.inference.script = [REPLY]
    assert asyncio.run(respond(inbound())).body == REPLY.text
    assert dict(wired.contexts[0].overrides) == {}
    assert [e["household"] for e in events(capsys.readouterr().out, "persona.overrides_unreachable")] == [str(HOME.id)]

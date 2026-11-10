"""Support for the blind page-voice tests. Every name the builder may rename is touched here and nowhere else: the
inbound factories, the persona prompt, the turn runner over fakes, the seeded database and the real app a voice route is
fetched from."""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

import pytest
from ashley import logs, services
from ashley.api.chat import inbound_from as chat_inbound
from ashley.api.chat_models import ChatMessage, KioskMessage
from ashley.api.kiosk import inbound_from as kiosk_inbound
from ashley.api.kiosk_device import KIOSK_COOKIE
from ashley.channels.devices import Devices, DevicesUnavailable
from ashley.channels.model import Device, DiscordServer, Inbound, Listed, Outbound, Satellite
from ashley.channels.respond import respond
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import Kind, NewTurn
from ashley.inference.inference import Inference
from ashley.inference.model import SystemPrompt, ToolCalls
from ashley.inference.reply import Reply
from ashley.live.live import Live
from ashley.main import create_app
from ashley.people.people import People
from ashley.persona import persona
from ashley.senses.presence import Presence
from ashley.runs.runs import NullRuns, Runs
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from ashley.tools.tools import Tools
from contract.conversations_support import events
from fastapi.testclient import TestClient
from pydantic import BaseModel
from respond_support import ALANA, HOME, Fakes

REAL_SYSTEM = persona.system
"""`persona.system` as the package has it, taken before any fixture replaces it."""

PUBLIC = "https://ashley.test"
KIOSK_TOKEN = "zqKIOSK-7731"
KIOSK = Device(7, HOME.id, "hall tablet", "hallway", "present", "text", "chat")
THREAD = f"person:{ALANA.id}:web"


# --- the tag and the offer ----------------------------------------------------------------------------------------


def chat_inbound_for(text: str = "is it raining", aloud: bool = True) -> Inbound:
    """What the web chat adapter hands in for a message, tagged or typed."""
    return chat_inbound(SignedIn(1, ALANA), ChatMessage(text=text, said_aloud=aloud))


def kiosk_inbound_for(text: str = "is it raining", aloud: bool = True) -> Inbound:
    """What the kiosk adapter hands in for a message, tagged or typed."""
    return kiosk_inbound(KIOSK, KioskMessage(text=text, said_aloud=aloud))


def aloud_of(inbound: Inbound) -> bool:
    return bool(getattr(inbound, "said_aloud"))


# --- a turn over fakes --------------------------------------------------------------------------------------------


@pytest.fixture
def real_prompt(wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> Fakes:
    """`wired`, but the system prompt is the real persona's, so what the model is told can be read; the context each
    prompt was built from is still recorded in `wired.contexts`."""

    def system(kind: Kind, context: persona.Context) -> Mapping[str, SystemPrompt]:
        wired.contexts.append(context)
        return REAL_SYSTEM(kind, context)

    monkeypatch.setattr(persona, "system", system)
    return wired


def hers(wired: Fakes) -> list[NewTurn]:
    return [t for t in wired.conversations.added if t.author == "ashley"]


def run_turn(wired: Fakes, inbound: Inbound, script: list[ToolCalls | BaseModel | Exception],
             stored: int = 1) -> Outbound:
    """`respond` for `inbound` with the model scripted, then wait until `stored` of her turns are stored (a held line
    stores its answer in the background)."""
    logs.setup()
    wired.inference.script = list(script)

    async def go() -> Outbound:
        out = await respond(inbound)
        async with asyncio.timeout(5):
            while len(hers(wired)) < stored:
                await asyncio.sleep(0.02)
        await asyncio.sleep(0.05)
        return out

    return asyncio.run(go())


def system_text(wired: Fakes, step: int = 0) -> str:
    """Everything the model was told in the system prompt of its `step`th call."""
    prompt = wired.inference.prompts[step]
    return "\n".join(f"{p.stable}\n{p.moment}" for p in prompt.system.values())


def speak(spoken: str, text: str = "Text.", *, aloud: bool = True, answers: bool = True) -> Reply:
    return Reply(answers=answers, spoken=spoken, text=text, aloud=aloud)


def voice_aloud_lines(out: str) -> list[dict[str, str]]:
    return events(out, "voice.aloud")


def raw_lines(out: str, event: str) -> str:
    """The log lines of `event` as printed, for asserting what they do not contain."""
    return "\n".join(ln for ln in out.splitlines() if f"event={event}" in ln)


# --- the kiosk over fakes ------------------------------------------------------------------------------------------


@dataclass
class FakeDevices(Devices):
    down: bool = False

    async def by_token(self, token: str) -> Device | None:
        if self.down:
            raise DevicesUnavailable("down")
        return KIOSK if token == KIOSK_TOKEN else None

    async def allow(self, device_id: int) -> bool:
        return True

    async def satellites(self) -> list[Satellite]:
        return []

    async def discord_servers(self) -> list[DiscordServer]:
        return []

    async def of_household(self, household_id: int) -> list[Listed]:
        return []


def kiosk_client(wired: Fakes, devices: FakeDevices) -> TestClient:
    """The kiosk's routes over the respond fakes, paired with `KIOSK_TOKEN`."""
    app = create_app(Settings(database_url="", build_version="test", public_url=PUBLIC))
    services.unregister(Live)
    for interface, fake in ((People, wired.people), (Presence, wired.presence), (Conversations, wired.conversations),
                            (Inference, wired.inference), (Tools, wired.tools), (Devices, devices),
                            (InFlight, InFlight.null()), (Runs, NullRuns())):
        services.register(interface, fake)
    c = TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC})
    c.cookies.set(KIOSK_COOKIE, KIOSK_TOKEN)
    return c

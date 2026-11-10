"""Shared pieces of the persona-override blind contract tests: `ashley.md`-shaped fixture text built from marker lines,
the real file's sections read through `sections.parse`, and the PersonaOverrides and PersonaWriter services as
`ashley.wiring` registers them over a real database."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from contract.conversations_support import household, person
from fastapi.testclient import TestClient
from httpx2 import Response
from live_support import FakeLive
from respond_support import Fakes

from ashley import services
from ashley.api.person import person_signed_in
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.db.database import Database
from ashley.inference.inference import Inference
from ashley.live.live import Live
from ashley.main import create_app
from ashley.people.model import Person
from ashley.persona import prose, sections
from ashley.persona.sections import Section
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from ashley.skills import config as skills_config
from ashley.skills.config import SkillsConfig
from ashley.skills.persona import NullPersonaOverrides, PersonaOverrides
from ashley.skills.persona_write import NullPersonaWriter, PersonaWriter
from ashley.tools.tools import Tools

CONFIG: SkillsConfig = skills_config.load()
PUBLIC = "https://ashley.test"
MARKER_START = "<!-- section"


def marker(section_id: str, override: str = "allowed", label: str | None = None) -> str:
    return f'<!-- section id={section_id} override={override} label="{label or section_id.title()}" -->'


def persona_file(*parts: tuple[str, str, str]) -> str:
    """A persona file of `(id, override, body)` parts, each marker on its own line above its body, a blank line
    between sections."""
    return "\n\n".join(f"{marker(i, o)}\n{body}" for i, o, body in parts) + "\n"


def without_markers(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.startswith(MARKER_START)).strip()


FIXTURE = persona_file(
    ("intro", "locked", "# Ashley\n\nYou are Ashley, the house's voice."),
    ("voice", "allowed", "Dry and warm. Short sentences."),
    ("examples", "locked", "## Examples\n\nSay `ok` when it is done."),
    ("reply", "allowed", "## Your reply\n\nOne field per medium."),
)
FIXTURE_ALLOWED = {"voice", "reply"}
FIXTURE_LOCKED = {"intro", "examples"}


def shipped_text() -> str:
    text = prose.read("default", "ashley.md")
    assert text is not None
    return text


def shipped_sections() -> tuple[Section, ...]:
    return sections.parse(shipped_text())


def allowed_id() -> str:
    found = sections.catalogue()
    assert found, "the shipped persona has no overridable section"
    return found[0].id


def second_allowed_id() -> str:
    found = sections.catalogue()
    assert len(found) >= 2, "the shipped persona has fewer than two overridable sections"
    return found[1].id


def locked_id() -> str:
    return next(s.id for s in shipped_sections() if s.override == "locked")


def parsed(text: str) -> dict[str, Section]:
    return {s.id: s for s in sections.parse(text)}


@asynccontextmanager
async def persona_services(url: str) -> AsyncGenerator[tuple[PersonaOverrides, PersonaWriter]]:
    """The services the wiring registers over `url`, with the database open."""
    create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC))
    db = services.get(Database)
    await db.open()
    try:
        read, write = services.get(PersonaOverrides), services.get(PersonaWriter)
        assert not isinstance(read, NullPersonaOverrides), "the wiring did not register PersonaOverrides"
        assert not isinstance(write, NullPersonaWriter), "the wiring did not register PersonaWriter"
        yield read, write
    finally:
        await db.close()


@dataclass(frozen=True)
class World:
    alana: Person
    sam: Person
    zed: Person


@dataclass
class Rig:
    client: TestClient
    w: World
    who: list[str]

    def as_(self, name: str) -> None:
        self.who[0] = name

    def get(self, path: str) -> Response:
        return self.client.get(path)

    def put(self, path: str, body: object) -> Response:
        return self.client.put(path, json=body)

    def post(self, path: str, body: object = None) -> Response:
        return self.client.post(path, json=body)


def build(url: str, fakes: Fakes, signed_in: bool = True) -> Rig:
    """The real app over `url`, signed in as Alana (`Rig.as_` changes who), with the channel fakes in the locator."""
    home, next_door = household(url, "home"), household(url, "next door")
    w = World(Person(person(url, home, "Alana"), home, "Alana"), Person(person(url, home, "Sam"), home, "Sam"),
              Person(person(url, next_door, "Zed"), next_door, "Zed"))
    app = create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC))
    rig = Rig(TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}), w, ["alana"])
    if signed_in:
        app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, getattr(w, rig.who[0]))
    services.register(Live, FakeLive())
    services.register(Conversations, fakes.conversations)
    services.register(InFlight, InFlight.null())
    services.register(Inference, fakes.inference)
    services.register(Tools, fakes.tools)
    return rig


def events(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, object]]:
    """The `fields` of each logged line named `event`."""
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.msg == event]


def everything_logged(caplog: pytest.LogCaptureFixture) -> str:
    return " ".join(f"{r.getMessage()} {getattr(r, 'fields', {})}" for r in caplog.records)


def at_info(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

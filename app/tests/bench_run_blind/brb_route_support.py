"""The bench routes through the real app on a real database, with a fake Sandbox and a person who can be switched."""

from dataclasses import dataclass, field
from typing import Any

from ashley import services
from ashley.api.person import person_signed_in
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.inference.inference import Inference
from ashley.live.live import Live
from ashley.main import create_app
from ashley.people.model import Person
from ashley.runs.sandbox import Sandbox
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from ashley.tools.tools import Tools
from brb_support import Box, Heard
from contract.conversations_support import household, person
from fastapi.testclient import TestClient
from respond_support import Fakes

PUBLIC = "https://ashley.test"


@dataclass
class Reply:
    status: int
    json: dict[str, Any]


@dataclass
class Rig:
    client: TestClient
    box: Box
    heard: Heard
    people: dict[str, Person]
    who: list[str] = field(default_factory=lambda: ["alana"])

    def as_(self, name: str) -> None:
        self.who[0] = name

    def post(self, path: str, body: object = None) -> Reply:
        got = self.client.post(path, json=body)
        return Reply(got.status_code, got.json())

    def get(self, path: str) -> Reply:
        got = self.client.get(path)
        return Reply(got.status_code, got.json())


def build(url: str, fakes: Fakes, box: Box | None = None, signed_in: bool = True) -> Rig:
    one, two = household(url, "one"), household(url, "two")
    people = {"alana": Person(person(url, one, "Alana"), one, "Alana"), "sam": Person(person(url, one, "Sam"), one, "Sam"),
              "zed": Person(person(url, two, "Zed"), two, "Zed")}
    app = create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC))
    made = Rig(TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}), box or Box(), Heard(), people)
    if signed_in:
        app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, made.people[made.who[0]])
    services.register(Live, made.heard)
    services.register(Conversations, fakes.conversations)
    services.register(InFlight, InFlight.null())
    services.register(Inference, fakes.inference)
    services.register(Tools, fakes.tools)
    services.register(Sandbox, made.box)
    return made

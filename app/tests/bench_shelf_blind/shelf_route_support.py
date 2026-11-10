"""The workshop's routes through the real app on a real database: two households, a signed-in person who can be
switched, a recording Live, and her chat fakes for the bench's talk."""

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
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from ashley.tools.tools import Tools
from fastapi.testclient import TestClient
from httpx2 import Response
from live_support import FakeLive
from respond_support import Fakes
from shelf_service_support import World, world

PUBLIC = "https://ashley.test"


@dataclass
class Rig:
    client: TestClient
    w: World
    live: FakeLive
    fakes: Fakes
    who: list[str] = field(default_factory=lambda: ["alana"])

    def as_(self, name: str) -> None:
        self.who[0] = name

    def post(self, path: str, body: object = None) -> "Reply":
        return Reply(self.client.post(path, json=body))

    def get(self, path: str) -> "Reply":
        return Reply(self.client.get(path))


@dataclass
class Reply:
    response: Response

    @property
    def status(self) -> int:
        return self.response.status_code

    @property
    def json(self) -> dict[str, Any]:
        body: dict[str, Any] = self.response.json()
        return body


def person_of(w: World, name: str) -> Person:
    owner = {"alana": w.alana, "sam": w.sam, "zed": w.zed}[name]
    return Person(owner.person_id, owner.household_id, name.capitalize())


def build(url: str, fakes: Fakes, signed_in: bool = True) -> Rig:
    w = world(url)
    app = create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC))
    rig = Rig(TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}), w, FakeLive(), fakes)
    if signed_in:
        app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, person_of(w, rig.who[0]))
    services.register(Live, rig.live)
    services.register(Conversations, fakes.conversations)
    services.register(InFlight, InFlight.null())
    services.register(Inference, fakes.inference)
    services.register(Tools, fakes.tools)
    return rig

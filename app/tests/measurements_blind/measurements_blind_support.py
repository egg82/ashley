"""Shared pieces of the measurements kind's blind contract tests: generators of well-formed bodies and of each way a
body is refused, and the real `decide` driven with the shipped rules."""

import json
from dataclasses import dataclass
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
from contract.conversations_support import household, person
from fastapi.testclient import TestClient
from httpx2 import Response
from live_support import FakeLive
from respond_support import Fakes
from ashley.workshop.commands import Add, Edit
from ashley.workshop.decide import EMPTY, Accepted, BenchState, Decision, Refused, decide
from ashley.workshop.measurements import MAX_REF, NAME, SOURCES, UNITS
from ashley.workshop.model import By, Text
from ashley.workshop.rules import Rules, load
from hypothesis import strategies as st

RULES: Rules = load()
ALANA = By(7)
KIND = "measurements"
MAX_CHARS = RULES.kinds[KIND].max_chars

names = st.from_regex(NAME, fullmatch=True)
units = st.sampled_from(sorted(UNITS))
sources = st.sampled_from(sorted(SOURCES))
numbers = st.one_of(st.floats(allow_nan=False, allow_infinity=False), st.integers(-10**9, 10**9))
tolerances = st.one_of(st.floats(min_value=0.0, allow_nan=False, allow_infinity=False), st.integers(0, 10**6))
refs = st.text(min_size=1, max_size=MAX_REF)


@st.composite
def item(draw: st.DrawFn, name: str | None = None) -> dict[str, Any]:
    """One well-formed item, with each optional key present or absent: a `bound` row always has a tolerance above 0,
    and only a `guessed` row may say whether it was `asked`."""
    out: dict[str, Any] = {"name": name if name is not None else draw(names), "value": draw(numbers),
                           "unit": draw(units), "source": draw(sources)}
    if out["source"] == "bound":
        out["tolerance"] = draw(tolerances.filter(lambda t: t > 0))
    elif draw(st.booleans()):
        out["tolerance"] = draw(tolerances)
    if draw(st.booleans()):
        out["ref"] = draw(refs)
    if out["source"] == "guessed" and draw(st.booleans()):
        out["asked"] = draw(st.booleans())
    return out


@st.composite
def item_lists(draw: st.DrawFn, min_size: int = 0, max_size: int = 6) -> list[dict[str, Any]]:
    """Well-formed items with distinct names."""
    chosen = draw(st.lists(names, min_size=min_size, max_size=max_size, unique=True))
    return [draw(item(name)) for name in chosen]


def body_of(items: object) -> str:
    return json.dumps({"items": items})


good_bodies = item_lists().map(body_of)

GOOD: dict[str, Any] = {"name": "width", "value": 12.5, "unit": "mm", "source": "measured"}


def with_(**changes: object) -> dict[str, Any]:
    """`GOOD` with the given keys replaced."""
    return {**GOOD, **changes}


def without(key: str) -> dict[str, Any]:
    return {k: v for k, v in GOOD.items() if k != key}


def decide_add(body: str, title: str = "t", state: BenchState = EMPTY) -> Decision:
    return decide(state, Add(ALANA, KIND, Text(title, body), "small"), RULES)


def decide_edit(state: BenchState, piece_id: int, base_version: int, body: str, title: str = "t") -> Decision:
    return decide(state, Edit(ALANA, piece_id, base_version, Text(title, body)), RULES)


def accepted(decision: Decision) -> Accepted:
    assert isinstance(decision, Accepted), f"expected an acceptance, got {decision}"
    return decision


def refused_as(decision: Decision) -> str:
    assert isinstance(decision, Refused), f"expected a refusal, got {decision}"
    return decision.reason


PUBLIC = "https://ashley.test"


@dataclass
class Rig:
    """The real app on a real database, with one signed-in person of household 1."""

    client: TestClient

    def post(self, path: str, body: object = None) -> Response:
        return self.client.post(path, json=body)

    def get(self, path: str) -> Response:
        return self.client.get(path)


def build(url: str, fakes: Fakes) -> Rig:
    h = household(url, "one")
    who = Person(person(url, h, "Alana"), h, "Alana")
    app = create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC))
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, who)
    services.register(Live, FakeLive())
    services.register(Conversations, fakes.conversations)
    services.register(InFlight, InFlight.null())
    services.register(Inference, fakes.inference)
    services.register(Tools, fakes.tools)
    return Rig(TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}))

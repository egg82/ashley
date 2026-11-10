"""`POST /api/messages` refusals before a reply: 401 `unauthorized` for a missing, malformed or unknown token, before
the body is read (so even a broken body is 401); 422 FastAPI's validation error for a body outside `MessageRequest`,
with nothing past sign-in touched; the edges `MessageRequest` allows are accepted."""

from typing import Any

import pytest
from messages_support import TOKEN, FakeDevices, app, bearer
from turns_support import World, world as world

UNAUTHORIZED: list[dict[str, str]] = [
    {}, {"Authorization": ""}, {"Authorization": "Bearer"}, {"Authorization": "Bearer "},
    {"Authorization": f"Basic {TOKEN}"}, {"Authorization": TOKEN}, {"Authorization": "Bearer not-a-device"},
    {"Authorization": f"Bearer {TOKEN}x"}, {"X-Token": TOKEN},
]


@pytest.mark.parametrize("headers", UNAUTHORIZED)
@pytest.mark.parametrize("payload", [{"text": "hi"}, {"text": ""}, {"nonsense": 1}])
def test_a_missing_malformed_or_unknown_token_is_401_before_anything_is_read(world: World, headers: dict[str, str],
                                                                             payload: dict[str, Any]) -> None:
    devices = FakeDevices()
    with app(world, devices) as c:
        r = c.post("/api/messages", json=payload, headers=headers)
    assert r.status_code == 401, r.text
    body = r.json()
    assert set(body) == {"code", "detail"} and body["code"] == "unauthorized"
    assert world.touched() == 0
    assert all(t != TOKEN for t in devices.asked)


def test_a_body_that_is_not_json_is_422_and_reads_nothing(world: World) -> None:
    devices = FakeDevices()
    with app(world, devices) as c:
        r = c.post("/api/messages", content=b"{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert world.touched() == 0 and devices.asked == []


INVALID: list[Any] = [
    {}, {"text": ""}, {"text": " "}, {"text": "\n\t "}, {"text": "x" * 4001}, {"text": 5}, {"text": None},
    {"text": "hi", "thread": ""}, {"text": "hi", "thread": "x" * 65}, {"text": "hi", "thread": "a b"},
    {"text": "hi", "thread": "a/b"}, {"text": "hi", "thread": "ä"}, {"text": "hi", "thread": "a\n"},
    {"text": "hi", "thread": 3}, {"text": "hi", "extra": 1}, {"thread": "a"}, ["hi"], "hi",
]


@pytest.mark.parametrize("payload", INVALID)
def test_a_body_outside_message_request_is_fastapis_422(world: World, payload: Any) -> None:
    with app(world, FakeDevices()) as c:
        r = c.post("/api/messages", json=payload, headers=bearer())
    assert r.status_code == 422, r.text
    assert isinstance(r.json()["detail"], list), "FastAPI's validation error, not the `refused` body"
    assert world.touched() == 0


def test_a_broken_json_body_is_422(world: World) -> None:
    with app(world, FakeDevices()) as c:
        r = c.post("/api/messages", content=b"{not json", headers={**bearer(), "Content-Type": "application/json"})
    assert r.status_code == 422
    assert world.touched() == 0


@pytest.mark.parametrize("payload", [
    {"text": "x" * 4000}, {"text": "x"}, {"text": " hi "}, {"text": "hi", "thread": "x" * 64},
    {"text": "hi", "thread": "A-z_0-9"}, {"text": "hi", "thread": None},
])
def test_the_edges_message_request_allows_are_accepted(world: World, payload: dict[str, Any]) -> None:
    with app(world, FakeDevices()) as c:
        r = c.post("/api/messages", json=payload, headers=bearer())
    assert r.status_code == 200, r.text
    assert world.conversations.turns_of(r.json()["conversation_id"])[0][2] == payload["text"]

"""Pins `GET /api/spend/routes` and `PUT /api/spend/routes/{task}` (`spend_routes`, `spend_routes_models`) over the app
and a real database for sessions: the household is always the session's, a refused choice is 422 `SpendRouteRefused` and
stores nothing, a choice is stored with who set it and shown back, an unreadable store is 503, and the refusal event
carries ids only. The household routes and the writer are scripted over a fake store."""

from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

import pytest
from ashley import services
from ashley.api.spend_routes_models import SpendRouteRefused, SpendRoutesResponse
from ashley.inference.household_routes import HouseholdRoutes
from ashley.inference.model import Task
from ashley.inference.route_choice_write import RouteChoiceWriter
from ashley.inference.route_choices import Choice, RoutesUnavailable
from fastapi.testclient import TestClient
from household_page.household_page_support import ORIGIN, People, app_client, as_, people_in
from household_routes_blind_support import SECRET, World, events, world

BASE = "/api/spend/routes"
B = {"route": {"provider": "b", "model": "m2"}}


@dataclass
class Writer(RouteChoiceWriter):
    """Writes into the world's store, keeping each `put`'s arguments; raises RoutesUnavailable while `down`."""

    w: World
    puts: list[tuple[int, int, Task, Choice | None]] = field(default_factory=list[tuple[int, int, Task, Choice | None]])
    down: bool = False

    async def put(self, household_id: int, person_id: int, task: Task, choice: Choice | None) -> None:
        if self.down:
            raise RoutesUnavailable("scripted")
        self.puts.append((household_id, person_id, task, choice))
        mine = self.w.store.choices.setdefault(household_id, {})
        if choice is None:
            mine.pop(task, None)
        else:
            mine[task] = choice


@pytest.fixture
def people(db_url: str) -> People:
    return people_in(db_url)


@dataclass
class Room:
    client: TestClient
    w: World
    writer: Writer


@pytest.fixture
def room(db_url: str, people: People) -> Generator[Room]:
    w = world()
    with app_client(db_url) as c:
        writer = Writer(w)
        services.register(HouseholdRoutes, w.layered)
        services.register(RouteChoiceWriter, writer)
        as_(c, people, "alana")
        yield Room(c, w, writer)


def put(r: Room, task: str, body: Any = B, headers: dict[str, str] = ORIGIN) -> Any:
    return r.client.put(f"{BASE}/{task}", json=body, headers=headers)


def shown(response: Any) -> SpendRoutesResponse:
    assert response.status_code == 200, response.text
    return SpendRoutesResponse.model_validate(response.json())


def test_the_room_lists_every_household_task_then_action_judge_and_the_bound(room: Room) -> None:
    body = shown(room.client.get(BASE))
    assert [t.task for t in body.choices] == ["chat", "brainstorm", "wrap_up", "action_judge"]
    assert body.refresh_s == 30
    chat = body.choices[0]
    assert chat.household and chat.chosen is None
    assert [(r.provider, r.model) for r in chat.routes] == [("a", "m1"), ("b", "m2")]
    assert {(r.provider, r.model) for r in chat.options} == {("a", "m1"), ("b", "m2"), ("c", "m3"), ("d", "m4")}
    judge = body.choices[-1]
    assert not judge.household and judge.options == [] and judge.chosen is None and judge.routes


def test_the_response_keeps_the_renamed_field(room: Room) -> None:
    raw = room.client.get(BASE).json()
    assert "choices" in raw and "tasks" not in raw and set(raw) == {"choices", "refresh_s"}
    assert set(SpendRoutesResponse.model_fields) == {"choices", "refresh_s"}


def test_options_are_those_whose_provider_is_wired_now(room: Room) -> None:
    room.w.wired.discard("c")
    chat = shown(room.client.get(BASE)).choices[0]
    assert ("c", "m3") not in {(r.provider, r.model) for r in chat.options}


def test_no_session_is_401_on_both(room: Room, people: People) -> None:
    as_(room.client, people, None)
    assert room.client.get(BASE).status_code == 401
    assert put(room, "chat").status_code == 401
    assert room.writer.puts == []


def test_a_choice_is_stored_for_the_sessions_household_and_person_and_shown_back(room: Room, people: People) -> None:
    body = shown(put(room, "chat"))
    assert room.writer.puts == [(people.home, people.alana, "chat", Choice("b", "m2"))]
    chat = body.choices[0]
    assert chat.chosen is not None and (chat.chosen.provider, chat.chosen.model) == ("b", "m2")
    assert shown(room.client.get(BASE)) == body


def test_the_person_stored_is_whoever_signed_in_and_the_household_is_theirs(room: Room, people: People) -> None:
    as_(room.client, people, "kim")
    shown(put(room, "wrap_up"))
    assert room.writer.puts == [(people.other, people.kim, "wrap_up", Choice("b", "m2"))]
    as_(room.client, people, "alana")
    assert shown(room.client.get(BASE)).choices[2].chosen is None


def test_a_choice_made_by_one_household_is_not_shown_to_another(room: Room, people: People) -> None:
    shown(put(room, "chat"))
    as_(room.client, people, "kim")
    assert shown(room.client.get(BASE)).choices[0].chosen is None
    as_(room.client, people, "sam")
    chosen = shown(room.client.get(BASE)).choices[0].chosen
    assert chosen is not None and (chosen.provider, chosen.model) == ("b", "m2")


def test_a_null_route_clears_the_choice(room: Room, people: People) -> None:
    shown(put(room, "chat"))
    body = shown(put(room, "chat", {"route": None}))
    assert room.writer.puts[-1] == (people.home, people.alana, "chat", None)
    assert body.choices[0].chosen is None


@pytest.mark.parametrize("task, body, reason", [
    ("command", B, "not_household"), ("action_judge", B, "not_household"), ("command", {"route": None}, "not_household"),
    ("chat", {"route": {"provider": "b", "model": "nope"}}, "not_offered"),
    ("chat", {"route": {"provider": "zz", "model": "m2"}}, "not_offered")])
def test_a_choice_the_task_does_not_offer_is_422_with_its_reason_and_nothing_is_stored(
        room: Room, task: str, body: Any, reason: str) -> None:
    got = put(room, task, body)
    assert got.status_code == 422, got.text
    refused = SpendRouteRefused.model_validate(got.json())
    assert refused.reason == reason and refused.detail
    assert room.writer.puts == []


def test_an_offered_model_whose_provider_has_no_key_is_422_unwired(room: Room) -> None:
    room.w.wired.discard("c")
    got = put(room, "chat", {"route": {"provider": "c", "model": "m3"}})
    assert got.status_code == 422 and SpendRouteRefused.model_validate(got.json()).reason == "unwired"
    assert room.writer.puts == []


def test_a_refusal_is_logged_with_ids_and_its_reason_only(room: Room, people: People,
                                                          info_logs: pytest.LogCaptureFixture) -> None:
    put(room, "command")
    refusals = events(info_logs, "inference.choice_refused")
    assert len(refusals) == 1
    assert refusals[0] == {"household": people.home, "person": people.alana, "task": "command",
                           "reason": "not_household"}
    assert SECRET not in info_logs.text


def test_a_body_outside_the_schema_is_a_validation_error_not_a_refusal(room: Room) -> None:
    for body in ({}, {"route": B["route"], "extra": 1}, {"route": {"provider": "", "model": "m"}},
                 {"route": {"provider": "a"}}):
        got = put(room, "chat", body)
        assert got.status_code == 422 and "reason" not in got.json()
    assert room.client.put(f"{BASE}/not_a_task", json=B, headers=ORIGIN).status_code == 422
    assert room.writer.puts == []


def test_a_write_from_another_site_is_403(room: Room) -> None:
    assert put(room, "chat", headers={"origin": "https://evil.test"}).status_code == 403
    assert room.writer.puts == []


def test_an_unreadable_store_is_503_unavailable_on_read_and_on_write(room: Room) -> None:
    room.w.store.down = True
    got = room.client.get(BASE)
    assert got.status_code == 503 and got.json()["code"] == "unavailable"
    room.w.store.down = False
    room.writer.down = True
    got = put(room, "chat")
    assert got.status_code == 503 and got.json()["code"] == "unavailable"
    assert room.writer.puts == []


def test_a_choice_set_here_reaches_a_call_once_the_bound_has_passed(room: Room, people: People) -> None:
    room.w.store.households[11] = people.home
    assert room.w.for_call(11) == room.w.layered.deployment()
    shown(put(room, "chat"))
    room.w.at(30)
    assert room.w.for_call(11).for_task("chat")[0].model == "m2"

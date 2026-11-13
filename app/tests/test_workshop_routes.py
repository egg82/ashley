"""The workshop routes through the real app over a real database: the kinds served from data; open, list, read and
close a bench; a command accepted (200) and refused (409, its reason); another person's bench is 404 on every route; a
closed bench takes no command or message (410); the bench's talk goes through the turn loop on its own thread, owner
only, and reads back; a bench's change on the live feed; an unwired workshop is 503."""

from collections.abc import Generator
from typing import Any

import psycopg
import pytest
from ashley import services
from ashley.api.bench_talk import inbound_for
from ashley.api.live import wire
from ashley.api.live_models import LiveBench
from ashley.api.chat_models import BenchMessage
from ashley.api.models import ChatConversation, ChatReply, ErrorResponse
from ashley.api.person import person_signed_in
from ashley.api.workshop_models import (BenchDetail, BenchList, BenchSummary, CommandApplied, CommandRefused,
                                        WorkshopKinds)
from ashley.channels.model import Inbound
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.inference.inference import Inference
from ashley.inference.reply import Reply
from ashley.live.events import BenchChanged, Shown
from ashley.main import create_app
from ashley.people.model import Person
from ashley.people.people import People
from ashley.runs.runs import NullRuns, Runs
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from ashley.workshop import rules
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi import FastAPI
from fastapi.testclient import TestClient
from respond_support import ALANA, SAM, Fakes, asked_last, wired as wired

PUBLIC = "https://ashley.test"
Json = dict[str, Any]


def seeded(url: str) -> None:
    """The household and people `respond_support` names, at their ids."""
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("INSERT INTO households (id, name) OVERRIDING SYSTEM VALUE VALUES (%s, 'home')",
                     (ALANA.household_id,))
        for who in (ALANA, SAM):
            conn.execute("INSERT INTO people (id, household_id, name) OVERRIDING SYSTEM VALUE VALUES (%s, %s, 'x')",
                         (who.id, who.household_id))


class As:
    """One app over the test database, its turn loop on fakes, signed in as whoever `__call__` names last."""

    def __init__(self, app: FastAPI, client: TestClient) -> None:
        self.app = app
        self.client = client

    def __call__(self, who: Person) -> TestClient:
        self.app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, who)
        return self.client


def _fakes(wired: Fakes) -> None:
    services.register(People, wired.people)
    services.register(Conversations, wired.conversations)
    services.register(InFlight, InFlight.null())
    services.register(Inference, wired.inference)


@pytest.fixture
def signed_in(db_url: str, wired: Fakes) -> Generator[As]:
    seeded(db_url)
    app = create_app(Settings(database_url=db_url, build_version="test", public_url=PUBLIC))
    with TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}) as client:
        _fakes(wired)
        yield As(app, client)
    services.unregister(Workshop)


def unwired_as(who: Person, wired: Fakes) -> TestClient:
    app = create_app(Settings(database_url="", build_version="test", public_url=PUBLIC))
    _fakes(wired)
    services.register(Runs, NullRuns())
    services.unregister(Workshop)
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, who)
    return TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC})


def opened(client: TestClient, title: str = "desk") -> BenchSummary:
    response = client.post("/api/benches", json={"title": title})
    assert response.status_code == 200
    return BenchSummary.model_validate(response.json())


def command(client: TestClient, bench_id: int, body: Json) -> tuple[int, Json]:
    response = client.post(f"/api/benches/{bench_id}/commands", json=body)
    return response.status_code, response.json()


ADD = {"type": "add", "kind": "note", "title": "parts", "body": "M3 screws", "size": "small"}


def test_the_kinds_are_served_from_the_data_file(wired: Fakes) -> None:
    got = WorkshopKinds.model_validate(unwired_as(ALANA, wired).get("/api/workshop/kinds").json())
    assert {k.name for k in got.kinds} == set(rules.load().kinds) and got.sizes == ["small", "medium", "large", "full"]


def test_each_kind_says_how_its_body_is_written(wired: Fakes) -> None:
    got = WorkshopKinds.model_validate(unwired_as(ALANA, wired).get("/api/workshop/kinds").json())
    assert {k.name: (k.format, k.language) for k in got.kinds} == {
        "document": ("markdown", None), "note": ("plain", None), "code": ("code", "text"),
        "model": ("code", "build123d"),
        "automation": ("automation", None), "wake": ("wake", None), "diagram": ("diagram", None), "measurements": ("measurements", None), "site": ("site", None),
        "video": ("video", None), "reader": ("reader", None), "recipe": ("recipe", None), "image": ("image", None), "file": ("file", None),
        "clip": ("clip", None), "audio": ("audio", None), "job": ("job", None)}


def test_the_list_carries_each_benchs_piece_count_and_last_change(signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    idle, busy = opened(alana, "idle"), opened(alana, "busy")
    assert (idle.piece_count, idle.last_changed_at) == (0, None)
    command(alana, busy.id, ADD)
    command(alana, busy.id, {**ADD, "title": "more"})
    command(alana, busy.id, {"type": "remove", "piece_id": 1})
    command(alana, busy.id, {"type": "edit", "piece_id": 9, "base_version": 1, "title": "x", "body": "y"})
    listed = {b.id: b for b in BenchList.model_validate(alana.get("/api/benches").json()).benches}
    at = BenchDetail.model_validate(alana.get(f"/api/benches/{busy.id}").json())
    assert (listed[idle.id].piece_count, listed[idle.id].last_changed_at) == (0, None)
    assert listed[busy.id].piece_count == 1 and at.bench.piece_count == 1
    assert listed[busy.id].last_changed_at is not None and listed[busy.id].last_changed_at == at.bench.last_changed_at


def test_a_piece_names_its_last_change_even_when_the_log_read_has_passed_it(signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana)
    command(alana, bench.id, ADD)
    command(alana, bench.id, {**ADD, "title": "busy"})
    for n in range(rules.load().recent_commands + 2):
        command(alana, bench.id, {"type": "edit", "piece_id": 2, "base_version": n + 1, "title": "busy", "body": str(n)})
    detail = BenchDetail.model_validate(alana.get(f"/api/benches/{bench.id}").json())
    assert 1 not in {r.seq for r in detail.recent}
    first, busy = detail.pieces
    assert (first.changed_by, first.changed_author, first.changed_person_id) == (1, "person", ALANA.id)
    assert busy.changed_by == detail.recent[-1].seq and busy.changed_at >= first.changed_at


def test_a_bench_opens_lists_takes_commands_and_reads_back(signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana)
    assert bench.thread == f"bench:{bench.id}"
    assert BenchList.model_validate(alana.get("/api/benches").json()).benches == [bench]
    status, body = command(alana, bench.id, ADD)
    assert status == 200 and CommandApplied.model_validate(body) == CommandApplied(seq=1, piece_id=1)
    edit = {"type": "edit", "piece_id": 1, "base_version": 1, "title": "parts", "body": "M4"}
    assert command(alana, bench.id, edit)[0] == 200
    status, body = command(alana, bench.id, edit)
    assert status == 409 and CommandRefused.model_validate(body).reason == "stale_base"
    detail = BenchDetail.model_validate(alana.get(f"/api/benches/{bench.id}").json())
    assert [(p.id, p.body, p.piece_version, p.placement.order) for p in detail.pieces] == [(1, "M4", 2, 0)]
    assert [(r.seq, r.type, r.outcome, r.author, r.person_id) for r in detail.recent] == [
        (1, "add", "accepted", "person", ALANA.id), (2, "edit", "accepted", "person", ALANA.id),
        (3, "edit", "stale_base", "person", ALANA.id)]


def test_another_persons_bench_is_404_on_every_route(signed_in: As, wired: Fakes) -> None:
    bench = opened(signed_in(ALANA))
    sam = signed_in(SAM)
    calls = [sam.get(f"/api/benches/{bench.id}"), sam.post(f"/api/benches/{bench.id}/close"),
             sam.post(f"/api/benches/{bench.id}/commands", json=ADD),
             sam.post(f"/api/benches/{bench.id}/messages", json={"text": "hi"}),
             sam.get(f"/api/benches/{bench.id}/conversation")]
    assert [(r.status_code, r.json()["code"]) for r in calls] == [(404, "not_found")] * len(calls)
    assert BenchList.model_validate(sam.get("/api/benches").json()).benches == []
    assert wired.conversations.calls == []


def test_a_closed_bench_is_kept_unlisted_and_takes_no_change(signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana)
    closed = BenchSummary.model_validate(alana.post(f"/api/benches/{bench.id}/close").json())
    assert closed.closed_at is not None
    assert BenchList.model_validate(alana.get("/api/benches").json()).benches == []
    assert alana.get(f"/api/benches/{bench.id}").status_code == 200
    for response in (alana.post(f"/api/benches/{bench.id}/commands", json=ADD),
                     alana.post(f"/api/benches/{bench.id}/messages", json={"text": "hi"})):
        assert response.status_code == 410 and ErrorResponse.model_validate(response.json()).code == "closed"


def test_the_benchs_talk_is_the_owners_brainstorm_on_its_own_thread(signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana)
    wired.inference.script = [Reply(spoken="Sure.", text="Sure!")]
    response = alana.post(f"/api/benches/{bench.id}/messages", json={"text": "what screws"})
    assert response.status_code == 200 and ChatReply.model_validate(response.json()).body == "Sure!"
    assert wired.conversations.calls[0] == ("for_thread", (ALANA.household_id, bench.thread, "brainstorm", (ALANA.id,)))
    talk = ChatConversation.model_validate(alana.get(f"/api/benches/{bench.id}/conversation").json())
    assert talk.thread == bench.thread and [t.text for t in talk.turns] == ["what screws", "Sure!"]


def test_the_inbound_is_the_owners_own_text_on_the_bench_thread() -> None:
    assert inbound_for(SignedIn(1, ALANA), 4, BenchMessage(text="hi")) == Inbound(
        household_id=ALANA.household_id, thread="bench:4", text="hi", kind="brainstorm", medium="text",
        audience="owner", speaker_id=ALANA.id, shared=False, place=None, channel="web", later=True, later_by="turn",
        bench_id=4, on_page=True, steers=True)


def test_a_message_naming_a_piece_the_person_just_added_tells_her_where_it_is_without_storing_the_note(
        signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana)
    status, applied = command(alana, bench.id, {**ADD, "kind": "document", "title": "Brief", "body": "the brief"})
    piece = CommandApplied.model_validate(applied).piece_id
    wired.inference.script = [Reply(spoken="ok", text="ok")]
    response = alana.post(f"/api/benches/{bench.id}/messages", json={"text": "here's the brief:", "piece_id": piece})
    assert status == 200 and response.status_code == 200
    asked = asked_last(wired.inference.prompts[0]).text
    assert asked.startswith("Alana: here's the brief:") and f"piece {piece}" in asked and "Brief" in asked
    assert [t.text for t in wired.conversations.added if t.author == "person"] == ["here's the brief:"]


def test_a_message_naming_a_piece_not_on_the_bench_is_refused_before_anything_is_said(signed_in: As,
                                                                                         wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana)
    response = alana.post(f"/api/benches/{bench.id}/messages", json={"text": "hi", "piece_id": 99})
    assert response.status_code == 422 and ErrorResponse.model_validate(response.json()).code == "refused"
    assert wired.conversations.calls == []


def test_a_bench_message_takes_no_attachment_since_its_paste_is_a_piece(signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana)
    response = alana.post(f"/api/benches/{bench.id}/messages", json={"text": "hi", "attachment": {"text": "x"}})
    assert response.status_code == 422 and wired.conversations.calls == []


def test_a_benchs_change_is_a_bench_event_on_the_feed() -> None:
    got = wire(BenchChanged(Shown(ALANA.household_id, ALANA.id), 4, 9)).root
    assert got == LiveBench(type="bench", bench_id=4, seq=9, by=None)
    assert wire(BenchChanged(Shown(ALANA.household_id, ALANA.id), 4, 9, "her")).root.by == "her"


def test_an_unwired_workshop_is_503(wired: Fakes) -> None:
    alana = unwired_as(ALANA, wired)
    for response in (alana.get("/api/benches"), alana.post("/api/benches", json={"title": "x"}),
                     alana.get("/api/benches/1"), alana.post("/api/benches/1/commands", json=ADD)):
        assert response.status_code == 503 and response.json()["code"] == "unavailable"


def test_move_remove_and_undo_arrive_as_the_persons_commands(signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana)
    command(alana, bench.id, ADD)
    command(alana, bench.id, {**ADD, "title": "tools"})
    moved = {"type": "move", "piece_id": 2, "placement": {"order": 0, "size": "full"}}
    assert command(alana, bench.id, moved) == (200, {"seq": 3, "piece_id": 2})
    assert command(alana, bench.id, {"type": "remove", "piece_id": 1})[0] == 200
    assert command(alana, bench.id, {"type": "undo", "seq": 4}) == (200, {"seq": 5, "piece_id": 1})
    detail = BenchDetail.model_validate(alana.get(f"/api/benches/{bench.id}").json())
    assert [(p.id, p.placement.order, p.placement.size) for p in detail.pieces] == [(2, 0, "full"), (1, 1, "small")]
    assert [r.type for r in detail.recent] == ["add", "add", "move", "remove", "undo"]
    assert detail.undo_next == 3


NUL_BODIES = [{**ADD, "title": "a\u0000b"}, {**ADD, "body": "a\u0000b"}, {**ADD, "kind": "no\u0000te"},
              {"type": "edit", "piece_id": 1, "base_version": 1, "title": "t", "body": "a\u0000b"},
              {"type": "edit", "piece_id": 1, "base_version": 1, "title": "a\u0000b", "body": "b"}]


@pytest.mark.parametrize("body", NUL_BODIES)
def test_a_nul_in_a_command_is_422_before_a_command_exists(signed_in: As, wired: Fakes, body: Json) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana)
    command(alana, bench.id, ADD)
    status, _ = command(alana, bench.id, body)
    assert status == 422
    assert [r.type for r in BenchDetail.model_validate(alana.get(f"/api/benches/{bench.id}").json()).recent] == ["add"]


def test_a_nul_in_a_bench_message_is_422(signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana)
    assert alana.post(f"/api/benches/{bench.id}/messages", json={"text": "a\u0000b"}).status_code == 422

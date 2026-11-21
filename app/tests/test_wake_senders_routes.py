"""A wake rule piece shows which installed automations send its event, and an installed automation whose wake action
names an event no wake rule on an open bench answers shows it: read from what the install wrote to the house, so an
edit after installing changes neither, and an uninstall takes the automation out of both."""

import json
from collections.abc import Generator

import pytest
from ashley import services
from ashley.api.workshop_models import BenchDetail, BenchPiece
from ashley.home_assistant.homes import Homes
from ashley.workshop.wake_links import Sender, WakeLinks
from automations_support import FakeHouse
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from homes_support import AnyHousehold
from install_support import CONFIG, body
from respond_support import ALANA, wired as wired
from test_workshop_install_routes import her_proposal
from test_workshop_routes import As, command, opened
from test_workshop_routes import signed_in as signed_in

WAKE = {"action": "rest_command.ashley_wake", "data": {"event": "gate_opened", "event_id": "{{ context.id }}"}}
SENDING = body(actions=[*CONFIG["actions"], WAKE])
RULE = json.dumps({"event": "gate_opened", "brief": "Say hello.", "tools": []})


@pytest.fixture
def house(signed_in: As) -> Generator[FakeHouse]:
    made = FakeHouse()
    services.register(Homes, AnyHousehold(made.house()))
    yield made
    services.unregister(Homes)


def read(client: TestClient, bench: int) -> BenchDetail:
    return BenchDetail.model_validate(client.get(f"/api/benches/{bench}").json())


def add(client: TestClient, bench: int, kind: str, title: str, text: str) -> None:
    command(client, bench, {"type": "add", "kind": kind, "title": title, "body": text, "size": "medium"})


def install(client: TestClient, bench: int, piece: int, seq: int) -> None:
    her_proposal(client, bench, piece)
    assert command(client, bench, {"type": "install", "piece_id": piece, "proposal": seq})[0] == 200


def piece(client: TestClient, bench: int, kind: str) -> BenchPiece:
    return next(p for p in read(client, bench).pieces if p.kind == kind)


def test_an_installed_automation_is_listed_on_the_rule_and_warned_of_until_a_rule_answers(signed_in: As,
                                                                                         house: FakeHouse) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    add(client, bench, "automation", "gate", SENDING)
    install(client, bench, 1, 2)
    shown = piece(client, bench, "automation").automation
    assert shown is not None and shown.unanswered_events == ["gate_opened"]
    add(client, bench, "wake", "greeting", RULE)
    rule = piece(client, bench, "wake")
    assert rule.wake is not None
    assert [(s.bench_id, s.piece_id, s.title) for s in rule.wake.senders] == [(bench, 1, "gate")]
    shown = piece(client, bench, "automation").automation
    assert shown is not None and shown.unanswered_events == []


def test_a_rule_for_another_event_has_no_senders_and_does_not_answer(signed_in: As, house: FakeHouse) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    add(client, bench, "automation", "gate", SENDING)
    install(client, bench, 1, 2)
    add(client, bench, "wake", "other", RULE.replace("gate_opened", "door_opened"))
    rule = piece(client, bench, "wake")
    assert rule.wake is not None and rule.wake.senders == []
    shown = piece(client, bench, "automation").automation
    assert shown is not None and shown.unanswered_events == ["gate_opened"]


def test_an_automation_never_installed_sends_nothing_and_a_note_has_no_wake(signed_in: As, house: FakeHouse) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    add(client, bench, "automation", "gate", SENDING)
    add(client, bench, "wake", "greeting", RULE)
    add(client, bench, "note", "n", "x")
    rule = piece(client, bench, "wake")
    assert rule.wake is not None and rule.wake.senders == []
    assert piece(client, bench, "note").wake is None
    shown = piece(client, bench, "automation").automation
    assert shown is not None and shown.unanswered_events == []


def test_the_install_decides_what_it_sends_not_the_piece_as_edited_afterwards(signed_in: As, house: FakeHouse) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    add(client, bench, "automation", "gate", SENDING)
    install(client, bench, 1, 2)
    add(client, bench, "wake", "greeting", RULE)
    command(client, bench, {"type": "edit", "piece_id": 1, "base_version": 1, "title": "gate", "body": body()})
    rule = piece(client, bench, "wake")
    assert rule.wake is not None and [s.piece_id for s in rule.wake.senders] == [1]


def test_an_uninstalled_automation_no_longer_sends(signed_in: As, house: FakeHouse) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    add(client, bench, "automation", "gate", SENDING)
    install(client, bench, 1, 2)
    add(client, bench, "wake", "greeting", RULE)
    assert command(client, bench, {"type": "undo", "seq": 3})[0] == 200
    rule = piece(client, bench, "wake")
    assert rule.wake is not None and rule.wake.senders == []
    shown = piece(client, bench, "automation").automation
    assert shown is not None and shown.unanswered_events == []


def test_unanswered_keeps_order_once_each_and_a_member_s_sender_has_no_title() -> None:
    links = WakeLinks(frozenset({"b"}), {"a": (Sender(1, 2, None),)})
    assert links.unanswered(("c", "a", "b", "c")) == ("c", "a")
    assert links.senders_of("a")[0].title is None and links.senders_of("z") == ()

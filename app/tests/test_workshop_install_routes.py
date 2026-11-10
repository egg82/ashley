"""Installing an automation piece through the real app over a real database and a fake HA: the bench shows her
proposal on the piece; the person's `install` command (`POST /api/benches/{id}/commands`) is answered once the house has
been written to and the piece shows how it went; Undo takes it back out of the house; a body outside HA's shape is
refused `bad_automation`, an install of a piece that is not an automation `not_installable`, of no proposal
`no_proposal`, and of a piece changed since `stale_base` (409, logged)."""

import asyncio
import json
from collections.abc import Generator

import pytest
from ashley import services
from ashley.api.workshop_models import BenchDetail, CommandRefused
from ashley.home_assistant.homes import Homes
from ashley.workshop.install_piece import automation_id_for
from ashley.workshop.model import Owner
from ashley.workshop.workshop import Workshop
from automations_support import FakeHouse
from homes_support import AnyHousehold
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from install_support import CONFIG, body, propose
from respond_support import ALANA, wired as wired
from test_workshop_routes import As, command, opened
from test_workshop_routes import signed_in as signed_in

AUTOMATION = {"type": "add", "kind": "automation", "title": "porch", "body": body(), "size": "medium"}
OWNER = Owner(ALANA.household_id, ALANA.id)


@pytest.fixture
def house(signed_in: As) -> Generator[FakeHouse]:
    made = FakeHouse()
    services.register(Homes, AnyHousehold(made.client()))
    yield made
    services.unregister(Homes)


def read(client: TestClient, bench: int) -> BenchDetail:
    return BenchDetail.model_validate(client.get(f"/api/benches/{bench}").json())


def her_proposal(bench: int, piece: int = 1, version: int = 1, enabled: bool = False) -> None:
    asyncio.run(services.get(Workshop).apply(OWNER, bench, propose(piece, version, enabled)))


def test_the_person_installs_her_proposal_and_undoes_it(signed_in: As, house: FakeHouse) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    command(client, bench, AUTOMATION)
    shown = read(client, bench).pieces[0].automation
    assert shown is not None and shown.install_proposal is None and shown.last_install is None
    her_proposal(bench)
    shown = read(client, bench).pieces[0].automation
    assert shown is not None and shown.install_proposal is not None
    assert (shown.install_proposal.seq, shown.install_proposal.piece_version, shown.install_proposal.enabled) == (2, 1, False)
    status, got = command(client, bench, {"type": "install", "piece_id": 1, "proposal": 2})
    assert (status, got) == (200, {"seq": 3, "piece_id": 1})
    ident = automation_id_for(bench, 1)
    assert house.configs[ident] == {"id": ident, **CONFIG} and house.enabled[house.entity_of(ident)] is False
    detail = read(client, bench)
    shown = detail.pieces[0].automation
    assert shown is not None and shown.install_proposal is None and shown.last_install is not None
    assert (shown.last_install.action, shown.last_install.automation_id, shown.last_install.install_ending) == ("install", ident, "done")
    assert detail.undo_next == 3 and detail.recent[-1].type == "install"
    status, _ = command(client, bench, {"type": "undo", "seq": 3})
    assert status == 200 and house.configs == {}
    shown = read(client, bench).pieces[0].automation
    assert shown is not None and shown.last_install is not None
    assert (shown.last_install.action, shown.last_install.install_ending) == ("uninstall", "done")


def test_a_note_carries_no_automation_and_cannot_be_installed(signed_in: As, house: FakeHouse) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    command(client, bench, {"type": "add", "kind": "note", "title": "n", "body": "x", "size": "small"})
    assert read(client, bench).pieces[0].automation is None
    status, got = command(client, bench, {"type": "install", "piece_id": 1, "proposal": 1})
    assert status == 409 and CommandRefused.model_validate(got).reason == "not_installable"


@pytest.mark.parametrize("text", ["{", json.dumps({"alias": "a", "id": "x"}), json.dumps({"triggers": "sun"})])
def test_a_body_outside_has_shape_is_refused_bad_automation(signed_in: As, house: FakeHouse, text: str) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    status, got = command(client, bench, {**AUTOMATION, "body": text})
    assert status == 409 and CommandRefused.model_validate(got).reason == "bad_automation"
    assert read(client, bench).pieces == []


def test_an_install_of_no_proposal_or_of_a_changed_piece_is_refused_and_writes_nothing(signed_in: As,
                                                                                        house: FakeHouse) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    command(client, bench, AUTOMATION)
    status, got = command(client, bench, {"type": "install", "piece_id": 1, "proposal": 1})
    assert status == 409 and CommandRefused.model_validate(got).reason == "no_proposal"
    her_proposal(bench)
    command(client, bench, {"type": "edit", "piece_id": 1, "base_version": 1, "title": "porch",
                            "body": body(alias="other")})
    status, got = command(client, bench, {"type": "install", "piece_id": 1, "proposal": 3})
    assert status == 409 and CommandRefused.model_validate(got).reason == "stale_base"
    shown = read(client, bench).pieces[0].automation
    assert shown is not None and shown.install_proposal is None
    assert house.writes == []

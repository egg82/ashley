"""A shadow run through the real app over a real database and a fake HA: her shadow proposal shows as one on the piece;
the person's `install` starts the run (the shadow, not the piece, goes into the house, and the piece's own install state
stays empty); what the house told is shown on the piece as would-have-fired beside did-fire; `undo` of the install stops
it, takes it out of the house and shows it ended."""

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from app_loop_support import on_app_loop
from ashley import services
from ashley.api.workshop_models import BenchDetail
from ashley.home_assistant.homes import Homes
from ashley.workshop import shadow
from ashley.workshop.install_piece import automation_id_for
from ashley.workshop.model import Owner
from ashley.workshop.shadows import Shadows
from ashley.workshop.workshop import Workshop
from automations_support import FakeHouse
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from homes_support import AnyHousehold
from install_support import body, propose
from respond_support import ALANA, wired as wired
from test_workshop_routes import As, command, opened
from test_workshop_routes import signed_in as signed_in

AUTOMATION = {"type": "add", "kind": "automation", "title": "porch", "body": body(), "size": "medium"}
OWNER = Owner(ALANA.household_id, ALANA.id)
AT = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


@pytest.fixture
def house(signed_in: As) -> Generator[FakeHouse]:
    made = FakeHouse()
    services.register(Homes, AnyHousehold(made.house()))
    yield made
    services.unregister(Homes)


def read(client: TestClient, bench: int) -> BenchDetail:
    return BenchDetail.model_validate(client.get(f"/api/benches/{bench}").json())


def test_the_bench_shows_a_shadow_run_from_proposal_to_its_end(signed_in: As, house: FakeHouse) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    command(client, bench, AUTOMATION)
    old = house.add("7e9f", "Alana is home")
    on_app_loop(client, services.get(Workshop).apply(OWNER, bench, propose(shadow=True, turn_off=old)))
    shown = read(client, bench).pieces[0].automation
    assert shown is not None and shown.install_proposal is not None and shown.install_proposal.shadow and shown.shadow is None

    status, _ = command(client, bench, {"type": "install", "piece_id": 1, "proposal": 2})
    assert status == 200
    ident = shadow.id_for(automation_id_for(bench, 1))
    assert set(house.configs) == {"7e9f", ident} and house.enabled == {old: True, house.entity_of(ident): True}
    shown = read(client, bench).pieces[0].automation
    assert shown is not None and shown.last_install is None and shown.install_proposal is None
    assert shown.shadow is not None and shown.shadow.ended_at is None and shown.shadow.replaces
    assert (shown.shadow.seq, shown.shadow.piece_version, shown.shadow.would, shown.shadow.did) == (3, 1, 0, 0)

    on_app_loop(client, services.get(Shadows).would(OWNER.household_id, bench, 1, AT, "c1"))
    on_app_loop(client, services.get(Shadows).did(OWNER.household_id, old, AT, "c2"))
    seen = read(client, bench).pieces[0].automation
    assert seen is not None and seen.shadow is not None
    assert (seen.shadow.would, seen.shadow.did, sorted(f.kind for f in seen.shadow.firings)) == (1, 1, ["did", "would"])

    status, _ = command(client, bench, {"type": "undo", "seq": 3})
    assert status == 200 and set(house.configs) == {"7e9f"}
    ended = read(client, bench).pieces[0].automation
    assert ended is not None and ended.shadow is not None and ended.shadow.ended_at is not None
    assert ended.last_install is None

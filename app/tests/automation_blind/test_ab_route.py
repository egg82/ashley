"""A person's install and undo through `POST /api/benches/{id}/commands` over the real app, a real database and the
fake house: what the house holds afterwards, what the bench shows on the piece, the refusals as 409, a retried request
that writes nothing twice, and that no route lets her install."""

from collections.abc import Generator

import pytest
from ab_support import CONFIG, body, edit, propose
from app_loop_support import on_app_loop
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
from respond_support import ALANA, SAM, wired as wired
from test_workshop_routes import As, command, opened
from test_workshop_routes import signed_in as signed_in

ADD = {"type": "add", "kind": "automation", "title": "porch", "body": body(), "size": "medium"}
OWNER = Owner(ALANA.household_id, ALANA.id)
OLD = "automation.old_porch"


@pytest.fixture
def house(signed_in: As) -> Generator[FakeHouse]:
    made = FakeHouse()
    made.add("old_porch", "Old porch", on=True)
    services.register(Homes, AnyHousehold(made.house()))
    yield made
    services.unregister(Homes)


def read(client: TestClient, bench: int) -> BenchDetail:
    return BenchDetail.model_validate(client.get(f"/api/benches/{bench}").json())


def by_her(client: TestClient, bench: int, piece: int = 1, version: int = 1, enabled: bool = False, turn_off: str | None = None) -> int:
    return on_app_loop(client, services.get(Workshop).apply(OWNER, bench, propose(piece, version, enabled, turn_off))).seq


def press(client: TestClient, bench: int, proposal: int, piece: int = 1) -> tuple[int, dict[str, object]]:
    return command(client, bench, {"type": "install", "piece_id": piece, "proposal": proposal})


def test_the_bench_shows_her_proposal_then_the_install_writes_exactly_what_was_proposed(signed_in: As,
                                                                                         house: FakeHouse) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    command(client, bench, ADD)
    shown = read(client, bench).pieces[0].automation
    assert shown is not None and shown.install_proposal is None and shown.last_install is None
    seq = by_her(client, bench, enabled=True, turn_off=OLD)
    shown = read(client, bench).pieces[0].automation
    assert shown is not None and shown.install_proposal is not None and shown.last_install is None
    assert (shown.install_proposal.seq, shown.install_proposal.piece_version, shown.install_proposal.enabled,
            shown.install_proposal.turn_off) == (seq, 1, True, OLD)
    assert house.writes == []
    status, got = press(client, bench, seq)
    assert status == 200 and got["piece_id"] == 1
    ident = automation_id_for(bench, 1)
    assert house.configs[ident] == {"id": ident, **CONFIG}
    assert house.enabled[house.entity_of(ident)] is True and house.enabled[OLD] is False
    shown = read(client, bench).pieces[0].automation
    assert shown is not None and shown.install_proposal is None and shown.last_install is not None
    last = shown.last_install
    assert (last.seq, last.action, last.automation_id, last.enabled, last.turn_off, last.install_ending) == (
        got["seq"], "install", ident, True, OLD, "done")
    assert last.finished_at is not None


def test_undo_through_the_route_takes_the_install_back_out_of_the_house(signed_in: As, house: FakeHouse) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    command(client, bench, ADD)
    _, got = press(client, bench, by_her(client, bench, turn_off=OLD))
    assert house.enabled[OLD] is False
    status, undone = command(client, bench, {"type": "undo", "seq": got["seq"]})
    assert status == 200
    assert set(house.configs) == {"old_porch"} and house.enabled == {OLD: True}
    last = read(client, bench).pieces[0].automation
    assert last is not None and last.last_install is not None
    assert (last.last_install.seq, last.last_install.action, last.last_install.install_ending) == (
        undone["seq"], "uninstall", "done")


def test_a_retried_install_request_is_refused_no_proposal_and_writes_nothing_more(signed_in: As,
                                                                                  house: FakeHouse) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    command(client, bench, ADD)
    seq = by_her(client, bench)
    assert press(client, bench, seq)[0] == 200
    writes = list(house.writes)
    status, body_ = press(client, bench, seq)
    assert status == 409 and CommandRefused.model_validate(body_).reason == "no_proposal"
    assert house.writes == writes


def test_refusals_are_409_with_their_reason_and_the_house_is_untouched(signed_in: As, house: FakeHouse) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    command(client, bench, ADD)
    command(client, bench, {"type": "add", "kind": "note", "title": "n", "body": "x", "size": "small"})
    command(client, bench, {**ADD, "body": body(triggers=[])})
    status, refused = command(client, bench, {**ADD, "body": "{not json"})
    assert status == 409 and CommandRefused.model_validate(refused).reason == "bad_automation"
    assert press(client, bench, 9)[0] == 409
    seq = by_her(client, bench)
    command(client, bench, {"type": "edit", "piece_id": 1, "base_version": 1, "title": "porch",
                            "body": body(alias="v2")})
    expect = {"stale": press(client, bench, seq), "none": press(client, bench, 99),
              "note": press(client, bench, seq, piece=2)}
    reasons = {k: CommandRefused.model_validate(v[1]).reason for k, v in expect.items()}
    assert reasons == {"stale": "stale_base", "none": "no_proposal", "note": "not_installable"}
    assert all(v[0] == 409 for v in expect.values())
    assert house.writes == []
    log = read(client, bench).recent
    assert [r.outcome for r in log[-3:]] == ["stale_base", "no_proposal", "not_installable"]


def test_a_piece_changed_since_the_proposal_is_stale_base_and_its_new_proposal_installs(signed_in: As,
                                                                                         house: FakeHouse) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    command(client, bench, ADD)
    old = by_her(client, bench)
    on_app_loop(client, services.get(Workshop).apply(OWNER, bench, edit(OWNER, 1, 1, alias="v2")))
    shown = read(client, bench).pieces[0].automation
    assert shown is not None and shown.install_proposal is None
    assert press(client, bench, old)[0] == 409
    assert press(client, bench, by_her(client, bench, version=2))[0] == 200
    assert house.configs[automation_id_for(bench, 1)]["alias"] == "v2"


def test_home_assistant_refusing_the_config_is_answered_200_and_the_piece_shows_refused_with_its_reason(
        signed_in: As, house: FakeHouse) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    command(client, bench, ADD)
    house.refuse = "invalid trigger"
    status, _ = press(client, bench, by_her(client, bench, turn_off=OLD))
    assert status == 200
    last = read(client, bench).pieces[0].automation
    assert last is not None and last.last_install is not None
    assert last.last_install.install_ending == "refused" and "invalid trigger" in (last.last_install.install_note or "")
    assert set(house.configs) == {"old_porch"} and house.enabled[OLD] is True


def test_an_install_over_an_automation_this_bench_never_installed_shows_failed_and_leaves_it_alone(
        signed_in: As, house: FakeHouse) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    command(client, bench, ADD)
    ident = automation_id_for(bench, 1)
    house.add(ident, "theirs", marker=1)
    theirs = dict(house.configs[ident])
    press(client, bench, by_her(client, bench, turn_off=OLD))
    last = read(client, bench).pieces[0].automation
    assert last is not None and last.last_install is not None and last.last_install.install_ending == "failed"
    assert house.configs[ident] == theirs and house.writes == [] and house.enabled[OLD] is True


def test_another_household_gets_404_for_an_install_and_nothing_is_written(signed_in: As, house: FakeHouse) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    command(client, bench, ADD)
    seq = by_her(client, bench)
    other = signed_in(SAM)
    status, _ = press(other, bench, seq)
    assert status == 404 and house.writes == []
    status, _ = command(other, bench, {"type": "undo", "seq": seq})
    assert status == 404 and house.writes == []


def test_the_commands_route_has_no_way_for_her_to_install(signed_in: As, house: FakeHouse) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    command(client, bench, ADD)
    seq = by_her(client, bench)
    status, _ = command(client, bench, {"type": "install", "piece_id": 1, "proposal": seq, "by": "ashley",
                                        "automation_id": "ashley_bench_1_piece_1"})
    assert status in (200, 409, 422)
    detail = read(client, bench)
    installs = [r for r in detail.recent if r.type == "install" and r.outcome == "accepted"]
    assert all(r.author == "person" for r in installs)

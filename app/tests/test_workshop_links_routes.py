"""Links through the real app over a real database: the link kinds served beside the piece kinds, a link and an unlink
arriving as the person's commands, a read carrying the links between pieces on the layout, and each link refusal a
409 with its reason."""

from ashley.api.workshop_models import BenchDetail, BenchLink, WorkshopKinds
from ashley.workshop import rules
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from respond_support import ALANA, Fakes, wired as wired
from test_workshop_routes import ADD, As, command, opened, unwired_as
from test_workshop_routes import signed_in as signed_in


def test_the_link_kinds_are_served_from_the_data_file(wired: Fakes) -> None:
    got = WorkshopKinds.model_validate(unwired_as(ALANA, wired).get("/api/workshop/kinds").json())
    assert {k.name: k.label for k in got.link_kinds} == dict(rules.load().link_kinds)
    assert {k.name for k in got.link_kinds} == {"part_of", "depends_on", "version_of"}


def test_a_link_and_an_unlink_arrive_as_the_persons_commands_and_the_read_carries_the_links(
        signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana)
    for title in ("plan", "step", "tool"):
        command(alana, bench.id, {**ADD, "title": title})
    link = {"type": "link", "from_id": 2, "kind": "part_of", "to_id": 1}
    assert command(alana, bench.id, link) == (200, {"seq": 4, "piece_id": 2})
    assert command(alana, bench.id, {**link, "from_id": 3, "kind": "depends_on", "to_id": 2})[0] == 200
    detail = BenchDetail.model_validate(alana.get(f"/api/benches/{bench.id}").json())
    assert detail.links == [BenchLink(from_id=2, kind="part_of", to_id=1), BenchLink(from_id=3, kind="depends_on", to_id=2)]
    assert [(r.type, r.piece_id) for r in detail.recent[-2:]] == [("link", 2), ("link", 3)]
    assert [p.changed_by for p in detail.pieces] == [1, 2, 3]
    assert command(alana, bench.id, {**link, "type": "unlink"}) == (200, {"seq": 6, "piece_id": 2})
    command(alana, bench.id, {"type": "archive", "piece_id": 2})
    assert BenchDetail.model_validate(alana.get(f"/api/benches/{bench.id}").json()).links == []
    command(alana, bench.id, {"type": "restore", "piece_id": 2})
    assert BenchDetail.model_validate(alana.get(f"/api/benches/{bench.id}").json()).links == [
        BenchLink(from_id=3, kind="depends_on", to_id=2)]


def test_each_link_refusal_is_409_with_its_reason(signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana)
    command(alana, bench.id, ADD)
    command(alana, bench.id, ADD)
    link = {"type": "link", "from_id": 2, "kind": "part_of", "to_id": 1}
    command(alana, bench.id, link)
    for body, why in [({**link, "to_id": 9}, "no_such_piece"), ({**link, "to_id": 2}, "bad_link"),
                      ({**link, "kind": "hologram"}, "bad_link"), (link, "already_linked"),
                      ({**link, "type": "unlink", "kind": "depends_on"}, "not_linked")]:
        status, raw = command(alana, bench.id, body)
        assert (status, raw["reason"]) == (409, why)
    assert command(alana, bench.id, {**link, "kind": ""})[0] == 422

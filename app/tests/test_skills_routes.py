"""A person's skill routes through the real app over a real database: a bench's kind of work set and cleared (a kind the
config does not list is 422, another person's bench 404); a skill read with its changelog (404 until one exists); pin,
rollback, and her waiting edit approved or declined (409 `stale` once the skill moved on); the kinds served."""

from ashley import services
from ashley.api.skill_models import SkillDetail, SkillRefusal
from ashley.api.workshop_models import BenchSummary, WorkshopKinds
from ashley.skills.skills import Skills
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from respond_support import ALANA, SAM, Fakes, wired as wired
from test_workshop_routes import As, opened
from test_workshop_routes import signed_in as signed_in


def test_a_bench_takes_a_kind_of_work_and_gives_it_up(signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana)
    assert bench.work is None
    seeded = {("3d", "3D"), ("code", "Code"), ("research", "Research"), ("writing", "Writing")}
    first = WorkshopKinds.model_validate(alana.get("/api/workshop/kinds").json())
    assert {(k.name, k.label) for k in first.work_kinds} == seeded
    assert alana.put(f"/api/benches/{bench.id}/work", json={"work": "knitting"}).status_code == 422
    set_ = alana.put(f"/api/benches/{bench.id}/work", json={"work": "code", "label": "Code"})
    assert set_.status_code == 200 and BenchSummary.model_validate(set_.json()).work == "code"
    assert alana.get(f"/api/benches/{bench.id}").json()["bench"]["work"] == "code"
    assert alana.put(f"/api/benches/{bench.id}/work", json={"work": "code"}).json()["work"] == "code"
    kinds = WorkshopKinds.model_validate(alana.get("/api/workshop/kinds").json())
    assert {(k.name, k.label) for k in kinds.work_kinds} == seeded
    assert alana.put(f"/api/benches/{bench.id}/work", json={"work": None}).json()["work"] is None
    assert alana.put(f"/api/benches/{bench.id}/work", json={"work": "Knit Ting", "label": "x"}).status_code == 422
    assert signed_in(SAM).put(f"/api/benches/{bench.id}/work", json={"work": "code"}).status_code == 404


def test_a_skill_is_read_pinned_rolled_back_and_her_waiting_edit_decided(signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    assert alana.get("/api/skills/knitting").status_code == 404
    assert alana.portal is not None
    shipped = SkillDetail.model_validate(alana.get("/api/skills/code").json())
    assert (shipped.skill_version, shipped.edits) == (0, 0) and shipped.body

    def hers(body: str, base: int) -> None:
        assert alana.portal is not None
        alana.portal.call(services.get(Skills).edit, ALANA.household_id, "code", body, "what", "why", base, None, None)

    hers("one", 0)
    hers("two", 1)
    read = SkillDetail.model_validate(alana.get("/api/skills/code").json())
    assert (read.skill_version, read.edits, read.body, read.pinned) == (2, 2, "two", False)
    back = SkillDetail.model_validate(alana.post("/api/skills/code/rollback", json={"to_version": 1}).json())
    assert (back.skill_version, back.body, back.changelog[0].restored_from) == (3, "one", 1)
    assert alana.post("/api/skills/code/rollback", json={"to_version": 9}).json()["reason"] == "no_such_version"
    assert alana.put("/api/skills/code/pin", json={"pinned": True}).json()["pinned"] is True
    hers("three", 3)
    held = SkillDetail.model_validate(alana.get("/api/skills/code").json())
    assert held.skill_version == 3 and held.waiting is not None and held.waiting_body == "three"
    approved = alana.post(f"/api/skills/code/proposals/{held.waiting.skill_version}/approve")
    assert approved.status_code == 200 and SkillDetail.model_validate(approved.json()).body == "three"
    again = alana.post(f"/api/skills/code/proposals/{held.waiting.skill_version}/approve")
    assert again.status_code == 409 and SkillRefusal.model_validate(again.json()).reason == "not_proposed"
    hers("four", 4)
    hers("five", 4)
    moved = SkillDetail.model_validate(alana.get("/api/skills/code").json())
    assert moved.waiting is not None
    alana.post("/api/skills/code/proposals/6/approve")
    stale = alana.post("/api/skills/code/proposals/5/approve")
    assert stale.status_code == 409 and stale.json()["reason"] == "stale"
    declined = alana.post("/api/skills/code/proposals/5/decline")
    assert declined.status_code == 200 and declined.json()["waiting"] is None

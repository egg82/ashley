"""The skills routes from `openapi.json` through the real app on a real database: who may call them, a bench's kind of
work, a skill with its changelog, pin, rollback, approve and decline, refusals as 409 with their reason, households
apart, and the kinds a screen offers."""

from collections.abc import Generator
from typing import Any

import pytest
from contract.conversations_support import run
from respond_support import Fakes
from respond_support import wired as wired
from skills_blind_support import CONFIG, Rig, build, skills

from ashley import services
from ashley.api.skill_models import SkillDetail, SkillRefusal
from ashley.api.workshop_models import BenchSummary, WorkshopKinds
from ashley.skills.skills import Skills

TARGET = "/api/skills"


@pytest.fixture
def rig(db_url: str, wired: Fakes) -> Generator[Rig]:
    made = build(db_url, wired)
    with made.client:
        yield made


def bench(rig: Rig, title: str = "b") -> int:
    got = rig.post("/api/benches", {"title": title})
    assert got.status_code == 200, got.text
    return int(BenchSummary.model_validate(got.json()).id)


def start(rig: Rig, kind: str, label: str = "Label") -> int:
    """A bench whose kind of work is `kind`, started with `label` when the household has none."""
    b = bench(rig)
    assert rig.put(f"/api/benches/{b}/work", {"work": kind, "label": label}).status_code == 200
    return b


def hers(rig: Rig, db_url: str, kind: str, body: str, base: int, person: int | None = None) -> None:
    """An edit through a service of its own over the same database."""
    async def scenario() -> None:
        async with skills(db_url, seeds={}) as s:
            household = rig.w.alana.household_id
            await s.edit(household, kind, body, "w", "y", base, None, person)

    run(scenario())


def detail(rig: Rig, kind: str) -> SkillDetail:
    got = rig.get(f"{TARGET}/{kind}")
    assert got.status_code == 200, got.text
    return SkillDetail.model_validate(got.json())


def refusal(got: Any) -> str:
    assert got.status_code == 409, got.text
    parsed = SkillRefusal.model_validate(got.json())
    assert parsed.code == "refused"
    return str(parsed.reason)


def test_every_route_needs_a_signed_in_person(db_url: str, wired: Fakes) -> None:
    rig = build(db_url, wired, signed_in=False)
    with rig.client:
        assert rig.put("/api/benches/1/work", {"work": None}).status_code == 401
        assert rig.get(f"{TARGET}/code").status_code == 401
        assert rig.put(f"{TARGET}/code/pin", {"pinned": True}).status_code == 401
        assert rig.post(f"{TARGET}/code/rollback", {"to_version": 0}).status_code == 401
        assert rig.post(f"{TARGET}/code/proposals/1/approve").status_code == 401
        assert rig.post(f"{TARGET}/code/proposals/1/decline").status_code == 401
        assert rig.get("/api/workshop/kinds").status_code == 401


# --- a bench's kind of work --------------------------------------------------------------------------------------


def test_a_new_slug_with_a_label_starts_a_kind_and_is_the_benchs_work(rig: Rig) -> None:
    b = bench(rig)
    got = rig.put(f"/api/benches/{b}/work", {"work": "electronics", "label": "Electronics"})
    assert got.status_code == 200
    assert BenchSummary.model_validate(got.json()).work == "electronics"
    kinds = WorkshopKinds.model_validate(rig.get("/api/workshop/kinds").json())
    assert {k.name: k.label for k in kinds.work_kinds}["electronics"] == "Electronics"
    listed = rig.get("/api/benches").json()["benches"]
    assert [x["work"] for x in listed if x["id"] == b] == ["electronics"]


def test_an_existing_kind_needs_no_label_and_keeps_its_own(rig: Rig) -> None:
    start(rig, "garden", "Garden")
    b = bench(rig)
    got = rig.put(f"/api/benches/{b}/work", {"work": "garden", "label": "Different"})
    assert got.status_code == 200 and BenchSummary.model_validate(got.json()).work == "garden"
    again = rig.put(f"/api/benches/{b}/work", {"work": "garden"})
    assert again.status_code == 200
    kinds = WorkshopKinds.model_validate(rig.get("/api/workshop/kinds").json())
    assert {k.name: k.label for k in kinds.work_kinds}["garden"] == "Garden"


def test_an_unknown_slug_without_a_label_is_422_and_changes_nothing(rig: Rig) -> None:
    b = bench(rig)
    got = rig.put(f"/api/benches/{b}/work", {"work": "electronics"})
    assert got.status_code == 422 and got.json()["code"] == "refused"
    assert rig.get(f"/api/benches/{b}").json()["bench"]["work"] is None
    kinds = WorkshopKinds.model_validate(rig.get("/api/workshop/kinds").json())
    assert "electronics" not in {k.name for k in kinds.work_kinds}


@pytest.mark.parametrize("work", ["Not A Slug", "-lead", "under_score", "x" * 41, "", "a/b"])
def test_a_slug_of_the_wrong_shape_is_422_even_with_a_label(rig: Rig, work: str) -> None:
    b = bench(rig)
    got = rig.put(f"/api/benches/{b}/work", {"work": work, "label": "Label"})
    assert got.status_code == 422
    kinds = WorkshopKinds.model_validate(rig.get("/api/workshop/kinds").json())
    assert work not in {k.name for k in kinds.work_kinds}


def test_the_longest_slug_is_accepted(rig: Rig) -> None:
    b = bench(rig)
    slug = "a" * CONFIG.max_slug_chars
    assert rig.put(f"/api/benches/{b}/work", {"work": slug, "label": "L"}).status_code == 200


@pytest.mark.parametrize("label", ["", "   ", "x" * 61])
def test_a_bad_label_for_a_new_kind_is_422(rig: Rig, label: str) -> None:
    b = bench(rig)
    assert rig.put(f"/api/benches/{b}/work", {"work": "electronics", "label": label}).status_code == 422
    assert rig.get(f"/api/benches/{b}").json()["bench"]["work"] is None


def test_null_clears_the_kind(rig: Rig) -> None:
    b = start(rig, "garden")
    got = rig.put(f"/api/benches/{b}/work", {"work": None})
    assert got.status_code == 200 and BenchSummary.model_validate(got.json()).work is None


def test_work_with_an_extra_field_or_a_nul_is_422(rig: Rig) -> None:
    b = bench(rig)
    assert rig.put(f"/api/benches/{b}/work", {"work": "code", "junk": 1}).status_code == 422
    assert rig.put(f"/api/benches/{b}/work", {"work": "new-kind", "label": "a\x00b"}).status_code == 422


def test_another_persons_bench_is_404_and_a_missing_bench_too(rig: Rig) -> None:
    b = bench(rig)
    rig.as_("sam")
    assert rig.put(f"/api/benches/{b}/work", {"work": "x-kind", "label": "X"}).status_code == 404
    assert rig.put("/api/benches/999999/work", {"work": None}).status_code == 404
    rig.as_("alana")
    assert rig.get(f"/api/benches/{b}").json()["bench"]["work"] is None


# --- the kinds a screen offers -----------------------------------------------------------------------------------


def test_work_kinds_are_the_households_own_and_the_next_door_does_not_see_them(rig: Rig) -> None:
    start(rig, "garden", "Garden")
    mine = {k["name"] for k in rig.get("/api/workshop/kinds").json()["work_kinds"]}
    rig.as_("sam")
    sams = {k["name"] for k in rig.get("/api/workshop/kinds").json()["work_kinds"]}
    rig.as_("zed")
    zeds = {k["name"] for k in rig.get("/api/workshop/kinds").json()["work_kinds"]}
    assert "garden" in mine and "garden" in sams and "garden" not in zeds


def test_work_kinds_are_empty_while_the_skills_cannot_be_reached(rig: Rig) -> None:
    start(rig, "garden", "Garden")
    services.register(Skills, Skills.null())
    got = rig.get("/api/workshop/kinds")
    assert got.status_code == 200
    assert got.json()["work_kinds"] == []
    assert got.json()["kinds"]


# --- reading a skill ---------------------------------------------------------------------------------------------


def test_an_unknown_kind_is_404(rig: Rig) -> None:
    got = rig.get(f"{TARGET}/nope")
    assert got.status_code == 404 and got.json()["code"] == "not_found"


def test_a_started_kind_with_no_skill_yet_is_404(rig: Rig) -> None:
    start(rig, "garden")
    assert rig.get(f"{TARGET}/garden").status_code == 404


def test_a_skill_reads_with_its_label_version_body_edits_and_changelog(rig: Rig, db_url: str) -> None:
    start(rig, "garden", "Garden planning")
    hers(rig, db_url, "garden", "ONE", 0, person=rig.w.alana.person_id)
    hers(rig, db_url, "garden", "TWO", 1)
    d = detail(rig, "garden")
    assert (d.kind, d.label, d.skill_version, d.body, d.edits, d.pinned, d.seeded_from) == (
        "garden", "Garden planning", 2, "TWO", 2, False, None)
    assert d.waiting is None and d.waiting_body is None
    assert [(v.skill_version, v.author, v.status, v.base_version, v.what, v.why) for v in d.changelog] == [
        (2, "ashley", "live", 1, "w", "y"), (1, "person", "live", 0, "w", "y")]


def test_a_sibling_in_the_household_reads_the_same_skill(rig: Rig, db_url: str) -> None:
    start(rig, "garden")
    hers(rig, db_url, "garden", "ONE", 0)
    rig.as_("sam")
    assert detail(rig, "garden").body == "ONE"


def test_another_household_gets_404_for_the_kind_and_its_pin_and_rollback(rig: Rig, db_url: str) -> None:
    start(rig, "garden")
    hers(rig, db_url, "garden", "ONE", 0)
    rig.as_("zed")
    assert rig.get(f"{TARGET}/garden").status_code == 404
    assert rig.put(f"{TARGET}/garden/pin", {"pinned": True}).status_code == 404
    assert rig.post(f"{TARGET}/garden/rollback", {"to_version": 0}).status_code == 404
    assert rig.post(f"{TARGET}/garden/proposals/1/approve").status_code == 404
    rig.as_("alana")
    assert detail(rig, "garden").pinned is False


# --- pin ---------------------------------------------------------------------------------------------------------


def test_pin_and_unpin_answer_with_the_skill(rig: Rig, db_url: str) -> None:
    start(rig, "garden")
    hers(rig, db_url, "garden", "ONE", 0)
    on = rig.put(f"{TARGET}/garden/pin", {"pinned": True})
    assert on.status_code == 200 and SkillDetail.model_validate(on.json()).pinned is True
    assert detail(rig, "garden").pinned is True
    off = rig.put(f"{TARGET}/garden/pin", {"pinned": False})
    assert SkillDetail.model_validate(off.json()).pinned is False


def test_pin_with_a_bad_body_is_422(rig: Rig, db_url: str) -> None:
    start(rig, "garden")
    hers(rig, db_url, "garden", "ONE", 0)
    assert rig.put(f"{TARGET}/garden/pin", {"pinned": "maybe"}).status_code == 422
    assert rig.put(f"{TARGET}/garden/pin", {}).status_code == 422
    assert rig.put(f"{TARGET}/garden/pin", {"pinned": True, "x": 1}).status_code == 422


def test_pin_of_an_unknown_kind_is_404(rig: Rig) -> None:
    assert rig.put(f"{TARGET}/nope/pin", {"pinned": True}).status_code == 404


def test_a_pinned_kind_shows_her_waiting_edit_with_its_body(rig: Rig, db_url: str) -> None:
    start(rig, "garden")
    hers(rig, db_url, "garden", "LIVE", 0)
    rig.put(f"{TARGET}/garden/pin", {"pinned": True})
    hers(rig, db_url, "garden", "WAITING", 1)
    d = detail(rig, "garden")
    assert (d.skill_version, d.body, d.edits) == (1, "LIVE", 1)
    assert d.waiting is not None and d.waiting.status == "proposed" and d.waiting.skill_version == 2
    assert d.waiting.author == "ashley" and d.waiting_body == "WAITING"
    assert [(v.skill_version, v.status) for v in d.changelog] == [(2, "proposed"), (1, "live")]


# --- rollback ----------------------------------------------------------------------------------------------------


def test_a_person_rolls_back_to_an_earlier_version_as_a_new_one(rig: Rig, db_url: str) -> None:
    start(rig, "garden")
    hers(rig, db_url, "garden", "ONE", 0)
    hers(rig, db_url, "garden", "TWO", 1)
    got = rig.post(f"{TARGET}/garden/rollback", {"to_version": 1})
    assert got.status_code == 200
    d = SkillDetail.model_validate(got.json())
    assert (d.skill_version, d.body, d.edits) == (3, "ONE", 3)
    top = d.changelog[0]
    assert (top.skill_version, top.restored_from, top.author, top.status) == (3, 1, "person", "live")
    assert top.why


def test_a_persons_rollback_is_live_even_on_a_pinned_kind(rig: Rig, db_url: str) -> None:
    start(rig, "garden")
    hers(rig, db_url, "garden", "ONE", 0)
    hers(rig, db_url, "garden", "TWO", 1)
    rig.put(f"{TARGET}/garden/pin", {"pinned": True})
    d = SkillDetail.model_validate(rig.post(f"{TARGET}/garden/rollback", {"to_version": 1}).json())
    assert (d.body, d.skill_version, d.waiting) == ("ONE", 3, None)


def test_rollback_refusals_are_409_with_the_reason(rig: Rig, db_url: str) -> None:
    start(rig, "garden")
    hers(rig, db_url, "garden", "ONE", 0)
    assert refusal(rig.post(f"{TARGET}/garden/rollback", {"to_version": 9})) == "no_such_version"
    assert refusal(rig.post(f"{TARGET}/garden/rollback", {"to_version": 0})) == "no_such_version"
    assert refusal(rig.post(f"{TARGET}/garden/rollback", {"to_version": 1})) == "unchanged"
    assert detail(rig, "garden").skill_version == 1


def test_rollback_with_a_bad_body_is_422(rig: Rig, db_url: str) -> None:
    start(rig, "garden")
    hers(rig, db_url, "garden", "ONE", 0)
    for body in ({"to_version": -1}, {}, {"to_version": "x"}, {"to_version": 0, "x": 1}):
        assert rig.post(f"{TARGET}/garden/rollback", body).status_code == 422


# --- approve, decline --------------------------------------------------------------------------------------------


def waiting(rig: Rig, db_url: str) -> int:
    start(rig, "garden")
    hers(rig, db_url, "garden", "LIVE", 0)
    rig.put(f"{TARGET}/garden/pin", {"pinned": True})
    hers(rig, db_url, "garden", "WAITING", 1)
    d = detail(rig, "garden")
    assert d.waiting is not None
    return d.waiting.skill_version


def test_approving_makes_her_edit_live(rig: Rig, db_url: str) -> None:
    v = waiting(rig, db_url)
    got = rig.post(f"{TARGET}/garden/proposals/{v}/approve")
    assert got.status_code == 200
    d = SkillDetail.model_validate(got.json())
    assert (d.body, d.skill_version, d.waiting, d.edits) == ("WAITING", v, None, 2)
    assert d.changelog[0].status == "live"


def test_declining_leaves_the_live_text_and_marks_it_declined(rig: Rig, db_url: str) -> None:
    v = waiting(rig, db_url)
    got = rig.post(f"{TARGET}/garden/proposals/{v}/decline")
    assert got.status_code == 200
    d = SkillDetail.model_validate(got.json())
    assert (d.body, d.skill_version, d.waiting, d.edits) == ("LIVE", 1, None, 1)
    assert [(c.skill_version, c.status) for c in d.changelog] == [(v, "declined"), (1, "live")]


def test_deciding_twice_or_a_version_that_does_not_wait_is_409_not_proposed(rig: Rig, db_url: str) -> None:
    v = waiting(rig, db_url)
    rig.post(f"{TARGET}/garden/proposals/{v}/approve")
    assert refusal(rig.post(f"{TARGET}/garden/proposals/{v}/approve")) == "not_proposed"
    assert refusal(rig.post(f"{TARGET}/garden/proposals/{v}/decline")) == "not_proposed"
    assert refusal(rig.post(f"{TARGET}/garden/proposals/1/decline")) == "not_proposed"
    assert refusal(rig.post(f"{TARGET}/garden/proposals/99/approve")) == "not_proposed"


def test_approving_after_the_skill_moved_on_is_409_stale(rig: Rig, db_url: str) -> None:
    v = waiting(rig, db_url)
    hers(rig, db_url, "garden", "PERSON-EDIT", 1, person=rig.w.alana.person_id)
    assert refusal(rig.post(f"{TARGET}/garden/proposals/{v}/approve")) == "stale"
    assert detail(rig, "garden").body == "PERSON-EDIT"
    assert rig.post(f"{TARGET}/garden/proposals/{v}/decline").status_code == 200


def test_deciding_on_an_unknown_kind_is_404(rig: Rig) -> None:
    assert rig.post(f"{TARGET}/nope/proposals/1/approve").status_code == 404
    assert rig.post(f"{TARGET}/nope/proposals/1/decline").status_code == 404


def test_a_sibling_may_approve_her_proposal(rig: Rig, db_url: str) -> None:
    v = waiting(rig, db_url)
    rig.as_("sam")
    assert rig.post(f"{TARGET}/garden/proposals/{v}/approve").status_code == 200
    assert detail(rig, "garden").body == "WAITING"


# --- the skills unreachable --------------------------------------------------------------------------------------


def test_the_routes_answer_503_while_the_skills_cannot_be_reached(rig: Rig, db_url: str) -> None:
    start(rig, "garden")
    hers(rig, db_url, "garden", "ONE", 0)
    services.register(Skills, Skills.null())
    assert rig.get(f"{TARGET}/garden").status_code == 503
    assert rig.put(f"{TARGET}/garden/pin", {"pinned": True}).status_code == 503
    assert rig.post(f"{TARGET}/garden/rollback", {"to_version": 0}).status_code == 503
    assert rig.post(f"{TARGET}/garden/proposals/1/approve").status_code == 503
    b = bench(rig)
    assert rig.put(f"/api/benches/{b}/work", {"work": "x-kind", "label": "X"}).status_code == 503


def test_a_pinned_kind_with_no_live_skill_shows_her_first_proposal_and_can_be_approved(rig: Rig, db_url: str) -> None:
    """A kind started and pinned before any edit: her first edit waits as a proposal, and the person must be able to
    see it and approve it from the routes."""
    start(rig, "garden")
    assert rig.put(f"{TARGET}/garden/pin", {"pinned": True}).status_code in (200, 404)
    hers(rig, db_url, "garden", "FIRST", 0)
    seen = rig.get(f"{TARGET}/garden")
    assert seen.status_code == 200, seen.text
    d = SkillDetail.model_validate(seen.json())
    assert d.waiting is not None and d.waiting_body == "FIRST" and d.skill_version == 0
    approved = rig.post(f"{TARGET}/garden/proposals/{d.waiting.skill_version}/approve")
    assert approved.status_code == 200 and SkillDetail.model_validate(approved.json()).body == "FIRST"

"""A tap is refused with a typed reason, and nothing runs, now or when a runner later resumes work: for another
person, another household, an expired proposal, one already carried out, and one that never was. A refusal consumes
nothing: the right person can still agree."""

import pytest
from agree_tap_blind_support import OK, REASON_KEY, REASONS, REFUSED_STATUSES, World, held_calls, world
from httpx2 import Response


def refused(got: Response, case: str) -> None:
    assert got.status_code in REFUSED_STATUSES, f"{case}: {got.status_code}"
    assert got.json()[REASON_KEY] == REASONS[case]


def nothing_ran(w: World) -> None:
    w.settle()
    assert w.tools.ran == [] and w.model.calls == 0 and w.work_rows() == 0


def test_another_person_of_the_household_is_refused_and_the_owner_can_still_agree(db_url: str) -> None:
    with world(db_url) as w:
        pid = w.hold(w.alana)
        refused(w.tap(w.sam, pid), "other_person")
        nothing_ran(w)
        assert w.pending(w.alana)
        assert w.tap(w.alana, pid).status_code == OK
        w.settle()
        assert len(w.tools.ran) == len(held_calls())


def test_a_person_of_another_household_is_refused_and_the_owner_can_still_agree(db_url: str) -> None:
    with world(db_url) as w:
        pid = w.hold(w.alana)
        refused(w.tap(w.zed, pid), "other_household")
        nothing_ran(w)
        assert w.pending(w.alana)
        assert w.tap(w.alana, pid).status_code == OK


def test_an_expired_proposal_is_refused(db_url: str) -> None:
    with world(db_url) as w:
        pid = w.hold(w.alana)
        w.age(pid)
        refused(w.tap(w.alana, pid), "expired")
        nothing_ran(w)


def test_an_unknown_proposal_is_refused(db_url: str) -> None:
    with world(db_url) as w:
        w.hold(w.alana)
        refused(w.tap(w.alana, 987_654), "unknown")
        nothing_ran(w)
        assert w.pending(w.alana)


def test_a_proposal_already_carried_out_is_refused_and_does_not_run_again(db_url: str) -> None:
    with world(db_url) as w:
        pid = w.hold(w.alana)
        assert w.tap(w.alana, pid).status_code == OK
        w.settle()
        assert len(w.tools.ran) == 2
        refused(w.tap(w.alana, pid), "carried")
        w.settle()
        assert len(w.tools.ran) == 2 and w.model.calls == 0


def test_a_tap_for_an_older_proposal_does_not_run_the_newer_one(db_url: str) -> None:
    with world(db_url) as w:
        old = w.hold(w.alana)
        new = w.hold(w.alana, held_calls()[1:])
        assert new != old
        refused(w.tap(w.alana, old), "carried")
        nothing_ran(w)
        assert w.pending(w.alana)


@pytest.mark.parametrize("body", [{}, {"proposal_id": "x"}, {"proposal_id": None}, {"proposal_id": 1.5}])
def test_a_body_without_a_proposal_id_runs_nothing(db_url: str, body: dict[str, object]) -> None:
    with world(db_url) as w:
        w.hold(w.alana)
        got = w.tap(w.alana, 1, body=body)
        assert got.status_code == 422
        nothing_ran(w)
        assert w.pending(w.alana)

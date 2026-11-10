"""The person the proposal was held for taps Agree: the held calls are carried out, as stored, once, with no model
asked, in a turn that is theirs, has no text and no taint."""

from agree_tap_blind_support import GARAGE, LAMP, OK, ROOM, SUMMARY, agree_of, held_calls, world
from ashley.senses.proposal_payloads import HeldCall


def test_the_rig_holds_a_proposal_that_is_pending_and_nothing_has_run(db_url: str) -> None:
    with world(db_url) as w:
        w.hold(w.alana)
        assert w.pending(w.alana) and w.tools.ran == [] and w.model.calls == 0 and w.work_rows() == 0


def test_agreeing_carries_out_the_held_calls_as_stored_in_order_once(db_url: str) -> None:
    with world(db_url) as w:
        pid = w.hold(w.alana)
        assert w.tap(w.alana, pid).status_code == OK
        w.settle()
        assert [(c.name, dict(c.arguments)) for c in w.tools.ran] == [
            (c.tool, dict(c.arguments)) for c in held_calls()]
        assert [c.name for c in w.tools.ran] == [LAMP.name, GARAGE.name]


def test_the_proposal_is_consumed_by_agreeing(db_url: str) -> None:
    with world(db_url) as w:
        pid = w.hold(w.alana)
        w.tap(w.alana, pid)
        w.settle()
        assert not w.pending(w.alana)


def test_no_model_is_asked_to_carry_out_a_tap(db_url: str) -> None:
    with world(db_url) as w:
        w.tap(w.alana, w.hold(w.alana))
        w.settle()
        assert w.model.calls == 0 and len(w.tools.ran) == 2


def test_agreeing_to_one_call_runs_that_call_only(db_url: str) -> None:
    with world(db_url) as w:
        w.tap(w.alana, w.hold(w.alana, (HeldCall("garage", {"door": 1}, "Move the garage door"),)))
        w.settle()
        assert [(c.name, dict(c.arguments)) for c in w.tools.ran] == [("garage", {"door": 1})]


def test_the_turn_is_the_tapping_persons_own_command_with_no_text_and_no_taint(db_url: str) -> None:
    with world(db_url) as w:
        pid = w.hold(w.alana)
        w.tap(w.alana, pid)
        saved = w.checkpoint()
        inbound = saved.inbound
        assert agree_of(inbound) == pid
        assert inbound.text == "" and inbound.taint is None and saved.tainted is None
        assert inbound.author == "person" and inbound.speaker_id == w.alana.id and inbound.audience == "owner"
        assert inbound.thread == f"person:{w.alana.id}:web"


def test_the_stored_turn_carries_none_of_the_held_calls_content(db_url: str) -> None:
    with world(db_url) as w:
        assert w.tap(w.alana, w.hold(w.alana)).status_code == OK
        w.settle()
        assert len(w.begun) == 1
        assert not any(ROOM in t or SUMMARY in t for t in w.person_turn_texts())

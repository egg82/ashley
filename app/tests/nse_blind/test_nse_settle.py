"""`settle`: how a turn that ended after its held line is settled, whether its work survives, and what is said."""

from collections.abc import Generator

import pytest
from ashley import services
from ashley.channels import unsaid
from ashley.channels.live_turn import Showing
from ashley.channels.model import Inbound, Medium
from ashley.channels.settled import Ended, settle
from ashley.channels.outbox import OutboxUnavailable
from ashley.conversations.conversations import ConversationError
from ashley.conversations.inflight import ClaimLost, InFlightUnavailable
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.live.events import ThreadTurn, TurnFailed
from ashley.live.live import Live
from ashley.people.model import Person
from contract.conversations_support import run
from later_support import FakeOutbox, Logged
from live_support import FakeLive
from nse_blind_support import Recording

CONVERSATION, SAID = 5, 11
WHO = Person(3, 1, "Alana")
RETRY_S = 77.0


@pytest.fixture
def live() -> Generator[FakeLive]:
    made = FakeLive()
    services.register(Live, made)
    yield made
    services.unregister(Live)


def _inbound(later_by: str = "turn", medium: Medium = "spoken") -> Inbound:
    return Inbound(1, "web:3", "turn on the lamp", "chat", medium, "owner", 3, False, None, "web", later=True,
                   later_by="outbox" if later_by == "outbox" else "turn", opens_benches=True, on_page=True)


def _ended(inbound: Inbound | None = None) -> Ended:
    inbound = inbound or _inbound()
    return Ended(inbound, CONVERSATION, SAID, WHO, Showing(inbound))


def _settle(work: Recording, error: Exception, reason: str | None = "inference_unavailable",
            turn: Ended | None = None) -> bool:
    out: list[bool] = []

    async def go() -> None:
        out.append(await settle(work, error, reason, turn or _ended(), RETRY_S))

    run(go())
    return out[0]


def _recoveries(logged: Logged) -> list[tuple[str, str]]:
    return [(e["reason"], e["recovery"]) for e in logged.events("respond.ended")]


def test_an_unreachable_model_on_work_that_retries_is_told_once_and_deferred(live: FakeLive,
                                                                              capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    work = Recording()
    assert _settle(work, InferenceUnavailable("down")) is True
    assert len(work.said) == 1
    conversation_id, turn = work.said[0]
    assert (conversation_id, turn.author, turn.text, turn.follows, turn.answers) == (
        CONVERSATION, "ashley", unsaid.UNREACHABLE, True, SAID)
    assert work.marked == 1 and work.deferred == [RETRY_S] and work.dropped == 0
    assert _recoveries(logged) == [("inference_unavailable", "told_and_kept")]
    assert [e for e in live.published if isinstance(e, TurnFailed)] == []


def test_the_line_already_told_is_not_said_again_but_the_work_is_deferred(live: FakeLive,
                                                                          capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    work = Recording(told=True)
    assert _settle(work, InferenceUnavailable("down")) is True
    assert work.said == [] and work.marked == 0 and work.deferred == [RETRY_S]
    assert _recoveries(logged) == [("inference_unavailable", "kept")]


def test_the_line_is_queued_for_the_thread_when_replies_go_out_through_the_outbox(live: FakeLive,
                                                                                  outbox: FakeOutbox) -> None:
    work = Recording()
    inbound = _inbound("outbox")
    assert _settle(work, InferenceUnavailable("down"), turn=_ended(inbound)) is True
    assert [(h, t, o.body) for h, t, o in outbox.added] == [(1, "web:3", unsaid.UNREACHABLE)]
    assert outbox.added[0][2].conversation_id == CONVERSATION
    assert work.marked == 1


def test_a_line_that_cannot_be_stored_still_defers_the_work(live: FakeLive) -> None:
    work = Recording(say_error=ConversationError("closed"))
    assert _settle(work, InferenceUnavailable("down")) is True
    assert work.deferred == [RETRY_S] and work.dropped == 0


def test_work_that_does_not_retry_is_dropped_and_the_screens_are_told_it_failed(live: FakeLive,
                                                                                capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    work = Recording(keeps=False)
    assert _settle(work, InferenceUnavailable("down")) is False
    assert work.dropped == 1 and work.said == [] and work.deferred == []
    assert [(e.why) for e in live.published if isinstance(e, TurnFailed)] == ["unavailable"]
    assert _recoveries(logged) == [("inference_unavailable", "failed_shown")]


def test_a_refusal_drops_the_work_and_is_shown_as_refused(live: FakeLive) -> None:
    work = Recording()
    assert _settle(work, InferenceRefused("no"), reason="refused") is False
    assert work.dropped == 1 and work.deferred == [] and work.said == []
    assert [e.why for e in live.published if isinstance(e, TurnFailed)] == ["refused"]


def test_any_other_error_on_work_that_retries_drops_it_rather_than_keeping_it(live: FakeLive) -> None:
    work = Recording()
    assert _settle(work, RuntimeError("boom"), reason=None) is False
    assert work.dropped == 1 and work.deferred == []
    assert [e.why for e in live.published if isinstance(e, TurnFailed)] == ["unavailable"]


def test_work_that_cannot_be_deleted_survives_and_nothing_is_shown_failed(live: FakeLive,
                                                                          capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    work = Recording(keeps=False, drops_to=False)
    assert _settle(work, InferenceUnavailable("down")) is True
    assert [e for e in live.published if isinstance(e, TurnFailed)] == []
    assert _recoveries(logged) == [("inference_unavailable", "kept")]


def test_a_claim_lost_leaves_the_turn_to_the_runner_that_holds_it(live: FakeLive,
                                                                  capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    work = Recording()
    assert _settle(work, ClaimLost(), reason="claim_lost") is True
    assert work.dropped == 0 and work.said == [] and work.deferred == []
    assert [e for e in live.published if isinstance(e, TurnFailed)] == []
    assert _recoveries(logged) == [("claim_lost", "other_runner")]


def test_a_claim_lost_while_deferring_is_the_other_runners(live: FakeLive, capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    work = Recording(defer_error=ClaimLost())
    assert _settle(work, InferenceUnavailable("down")) is True
    assert work.dropped == 0
    assert _recoveries(logged) == [("inference_unavailable", "other_runner")]


def test_a_claim_lost_while_saying_the_line_is_the_other_runners(live: FakeLive) -> None:
    work = Recording(say_error=ClaimLost())
    assert _settle(work, InferenceUnavailable("down")) is True
    assert work.dropped == 0 and work.deferred == []


def test_a_defer_the_database_cannot_make_is_logged_and_the_work_still_survives(
        live: FakeLive, capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    work = Recording(defer_error=InFlightUnavailable("down"))
    assert _settle(work, InferenceUnavailable("down")) is True
    assert work.dropped == 0
    assert len(logged.events("respond.defer_failed")) == 1
    assert [e for e in live.published if isinstance(e, TurnFailed)] == []


def test_the_reason_defaults_when_none_is_given(live: FakeLive, capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    _settle(Recording(keeps=False), RuntimeError("x"), reason=None)
    got = logged.events("respond.ended")
    assert len(got) == 1 and got[0]["reason"] not in ("", "None")


def test_the_screens_are_told_the_line_was_stored_so_the_page_reads_it(live: FakeLive) -> None:
    assert _settle(Recording(), InferenceUnavailable("down")) is True
    assert [e.thread for e in live.published if isinstance(e, ThreadTurn)] == ["web:3"]


def test_the_screens_are_not_told_of_a_line_that_was_not_stored(live: FakeLive) -> None:
    assert _settle(Recording(say_error=ConversationError("closed")), InferenceUnavailable("down")) is True
    assert [e for e in live.published if isinstance(e, ThreadTurn)] == []


def test_an_outbox_that_cannot_be_reached_does_not_stop_the_work_being_kept(live: FakeLive,
                                                                            outbox: FakeOutbox) -> None:
    outbox.add_error = OutboxUnavailable("down")
    work = Recording()
    assert _settle(work, InferenceUnavailable("down"), turn=_ended(_inbound("outbox"))) is True
    assert work.marked == 1 and work.deferred == [RETRY_S] and work.dropped == 0

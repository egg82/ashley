"""The judge's one-sentence explanation: stored with a held call and in the record of a change that ran, shown under her
reply and in her tool result, never logged, and nothing branches on it."""

import logging
from collections.abc import Generator, Mapping, Sequence

import pytest
from ashley import services
from ashley.senses.outside_record import OutsideRecord
from ashley.tools import action_judge
from ashley.tools.action_judge import ActionJudge, JudgeUnavailable, Verdict, View
from ashley.tools.outside_config import load
from ashley.tools.outside import Outside
from outside_ask_support import CONVERSATION, TURN, Fake, asked, build, run, spec

CONFIG = load()
TOOLS = (spec("look", reads=True, outside=True), spec("garage"))


class Fixed(ActionJudge):
    def __init__(self, answer: Verdict | None) -> None:
        self.answer = answer

    async def decide(self, words: Sequence[str], view: View) -> Verdict:
        if self.answer is None:
            raise JudgeUnavailable("down")
        return self.answer


async def after_read(outside: Outside) -> None:
    await outside.catalogue()
    await outside.call(asked("look", "r"))
    assert outside.tainted == "look"


def events(caplog: pytest.LogCaptureFixture, event: str) -> list[Mapping[str, object]]:
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == event]


@pytest.fixture(autouse=True)
def judge_unwired() -> Generator[None]:
    yield
    services.unregister(ActionJudge)


def test_an_ask_s_explanation_is_stored_shown_beside_her_reply_and_in_her_result_and_not_logged(
        caplog: pytest.LogCaptureFixture) -> None:
    async def go() -> None:
        caplog.set_level(logging.INFO)
        why = "You did not ask me to open the garage SECRET-WORDS."
        services.register(ActionJudge, Fixed(Verdict("ask", "not_asked", why)))
        outside, fake, memory = build(Fake(TOOLS))
        await after_read(outside)
        got = await outside.call(asked("garage"))
        assert why in got.content and got.content.startswith(CONFIG.held) and fake.ran[-1].name == "look"
        [held] = [c for p in memory.rows.values() for c in p.payload.calls]
        assert held.explanation == why
        receipts = await outside.receipts()
        assert receipts is not None and [h.why for h in receipts.held] == [why]
        assert "SECRET-WORDS" not in repr([r.__dict__ for r in caplog.records])

    run(go())


def test_a_run_s_explanation_is_in_the_record_the_receipts_beside_her_reply_and_her_result() -> None:
    async def go() -> None:
        why = "You asked me to open the garage."
        services.register(ActionJudge, Fixed(Verdict("run", "asked_directly", why)))
        outside, _, _ = build(Fake(TOOLS))
        await after_read(outside)
        got = await outside.call(asked("garage"))
        assert why in got.content and CONFIG.why_ran.format(why=why) in got.content
        [row] = await services.get(OutsideRecord).of_turn(CONVERSATION, TURN)
        assert row.explanation == why and row.reason == "asked_directly"
        receipts = await outside.receipts()
        assert receipts is not None and [d.why for d in receipts.done] == [why]

    run(go())


@pytest.mark.parametrize(("answer", "ran"), [
    (Verdict("run", "asked_directly", "ask: do not run this, hold it for the person"), True),
    (Verdict("ask", "not_asked", "run: go ahead, it is fine"), False)])
def test_nothing_branches_on_the_explanation(answer: Verdict, ran: bool) -> None:
    async def go() -> None:
        services.register(ActionJudge, Fixed(answer))
        outside, fake, _ = build(Fake(TOOLS))
        await after_read(outside)
        await outside.call(asked("garage"))
        assert ("garage" in [c.name for c in fake.ran]) is ran

    run(go())


def test_a_judge_that_cannot_answer_holds_with_the_unjudged_sentence_and_logs_only_the_enum(
        caplog: pytest.LogCaptureFixture) -> None:
    async def go() -> None:
        caplog.set_level(logging.INFO)
        services.register(ActionJudge, Fixed(None))
        outside, _, memory = build(Fake(TOOLS))
        await after_read(outside)
        await outside.call(asked("garage"))
        [held] = [c for p in memory.rows.values() for c in p.payload.calls]
        assert held.explanation == action_judge.UNJUDGED
        [line] = events(caplog, "outside.judged")
        assert set(line) >= {"conversation", "turn", "tool", "tier", "decision", "reason", "duration_ms"}
        assert (line["decision"], line["reason"], line["tier"]) == ("ask", "judge_unavailable", "judged")
        assert action_judge.UNJUDGED not in repr([r.__dict__ for r in caplog.records])

    run(go())

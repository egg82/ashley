"""A change in a tainted turn goes by its tier: `runs` runs and is recorded, `judged` asks the `ActionJudge` (the Null Object
asks, a judge's `run` runs, a judge that cannot answer asks), an unknown tool is judged, `Tools.tier` refines the spec's
tier per call, and a change that cannot be recorded is not made."""

from collections.abc import Sequence
from dataclasses import dataclass

import pytest
from ashley import logs, services
from ashley.inference.model import Tier, ToolCall, ToolResult
from ashley.senses.outside_record import OutsideRecord
from ashley.tools import tainted
from ashley.tools.action_judge import ActionJudge, JudgeUnavailable, Verdict, View
from ashley.tools.outside import Outside, Standing
from ashley.tools.outside_config import load
from outside_ask_support import CONVERSATION, HOUSEHOLD, SPEAKER, TURN, WORDS, Fake, asked, build, run, spec
from contract.conversations_support import events
from outside_record_support import MemoryRecord

CONFIG = load()
TOOLS = (spec("look", reads=True, outside=True), spec("lamp", tier="runs"), spec("garage"), spec("both", tier="runs"))


class Judge(ActionJudge):
    def __init__(self, answer: Verdict | None) -> None:
        self.answer, self.asked = answer, 0
        self.seen: list[tuple[Sequence[str], View]] = []

    async def decide(self, words: Sequence[str], view: View) -> Verdict:
        self.asked += 1
        self.seen.append((words, view))
        if self.answer is None:
            raise JudgeUnavailable("down")
        return self.answer


@dataclass
class Refining(Fake):
    """A source that says `both` is judged when its arguments name a folder."""

    async def tier(self, call: ToolCall) -> Tier | None:
        return "judged" if call.name == "both" and "folder" in call.arguments else None


async def after_read(outside: Outside) -> None:
    await outside.catalogue()
    await outside.call(asked("look", "r"))
    assert outside.tainted == "look"


def test_a_runs_tier_change_runs_in_a_tainted_turn_and_is_recorded() -> None:
    async def go() -> None:
        outside, fake, memory = build(Fake(TOOLS))
        await after_read(outside)
        got = await outside.call(asked("lamp", a=1))
        assert got.content == "ok" and [c.name for c in fake.ran] == ["look", "lamp"] and memory.rows == {}
        rows = await services.get(OutsideRecord).of_turn(CONVERSATION, TURN)
        assert [(r.tool, r.tier, r.reason, r.household_id, r.person_id) for r in rows] == [
            ("lamp", "runs", None, HOUSEHOLD, SPEAKER)]
        assert "lamp" not in rows[0].summary and "a: 1" not in rows[0].summary
        assert await outside.receipts() is None

    run(go())


def test_the_receipts_list_the_judged_change_that_ran_and_not_the_runs_tier_ones() -> None:
    async def go() -> None:
        services.register(ActionJudge, Judge(Verdict("run", "asked_directly", "You asked for it.")))
        try:
            outside, _, _ = build(Fake(TOOLS))
            await after_read(outside)
            for name in ("lamp", "garage", "lamp"):
                assert (await outside.call(asked(name, f"c-{name}"))).content.startswith("ok")
            assert len(await services.get(OutsideRecord).of_turn(CONVERSATION, TURN)) == 3
            receipts = await outside.receipts()
            assert receipts is not None and receipts.held == ()
            assert [r.headline for r in receipts.done] == [CONFIG.unlabelled]
            assert [r.detail for r in receipts.done] == [CONFIG.unlabelled]
        finally:
            services.unregister(ActionJudge)

    run(go())


def test_a_judged_change_is_held_by_the_null_judge_and_nothing_is_recorded() -> None:
    async def go() -> None:
        services.unregister(ActionJudge)
        outside, fake, memory = build(Fake(TOOLS))
        await after_read(outside)
        got = await outside.call(asked("garage"))
        assert got.content.startswith(CONFIG.held) and [c.name for c in fake.ran] == ["look"]
        receipts = await outside.receipts()
        assert memory.proposed == 1 and receipts is not None and receipts.done == () and len(receipts.held) == 1

    run(go())


def test_a_judge_that_says_run_runs_the_call_and_the_record_keeps_why() -> None:
    async def go() -> None:
        verdict = Verdict("run", "asked_directly", "You asked for it.")
        judge = Judge(verdict)
        services.register(ActionJudge, judge)
        try:
            outside, fake, _ = build(Fake(TOOLS))
            await after_read(outside)
            got = await outside.call(asked("garage"))
            assert got.content == f"ok\n{CONFIG.why_ran.format(why='You asked for it.')}"
            assert [c.name for c in fake.ran] == ["look", "garage"]
            row = (await services.get(OutsideRecord).of_turn(CONVERSATION, TURN))[0]
            assert (row.tier, row.reason, row.explanation) == ("judged", "asked_directly", "You asked for it.")
            assert judge.seen == [(WORDS, View("garage"))]
        finally:
            services.unregister(ActionJudge)

    run(go())


@pytest.mark.parametrize("answer", [Verdict("ask", "not_asked", "You did not ask."), None])
def test_a_judge_that_asks_or_cannot_answer_holds_the_call(answer: Verdict | None) -> None:
    async def go() -> None:
        services.register(ActionJudge, Judge(answer))
        try:
            outside, fake, memory = build(Fake(TOOLS))
            await after_read(outside)
            held = (await outside.call(asked("garage"))).content
            assert held.startswith(CONFIG.held) and (answer is None or "You did not ask." in held)
            assert [c.name for c in fake.ran] == ["look"] and memory.proposed == 1
        finally:
            services.unregister(ActionJudge)

    run(go())


def test_a_tool_nobody_classified_is_judged_and_the_null_judge_holds_it() -> None:
    async def go() -> None:
        services.unregister(ActionJudge)
        outside, fake, _ = build(Fake(TOOLS))
        await after_read(outside)
        assert (await outside.call(asked("unheard_of"))).content.startswith(CONFIG.held)
        assert [c.name for c in fake.ran] == ["look"]

    run(go())


def test_the_source_can_refine_the_specs_tier_per_call() -> None:
    async def go() -> None:
        services.unregister(ActionJudge)
        outside, fake, _ = build(Refining(TOOLS))
        await after_read(outside)
        assert (await outside.call(asked("both", "c1"))).content == "ok"
        assert (await outside.call(asked("both", "c2", folder="trash"))).content.startswith(CONFIG.held)
        assert [c.name for c in fake.ran] == ["look", "both"]

    run(go())


def test_an_untainted_turn_runs_a_judged_change_and_records_nothing() -> None:
    async def go() -> None:
        outside, fake, _ = build(Fake(TOOLS))
        assert (await outside.call(asked("garage"))).content == "ok" and [c.name for c in fake.ran] == ["garage"]
        assert await outside.receipts() is None and (await services.get(OutsideRecord).of_turn(CONVERSATION, TURN)) == ()

    run(go())


def test_a_change_that_cannot_be_recorded_for_want_of_a_speaker_is_not_made() -> None:
    async def go() -> None:
        outside, fake, _ = build(Fake(TOOLS), standing=None)
        await after_read(outside)
        got = await outside.call(asked("lamp"))
        assert got.is_error and [c.name for c in fake.ran] == ["look"]

    run(go())


def test_an_unwritable_record_does_not_stop_the_change_and_the_reply_still_shows_a_judged_one_only() -> None:
    async def go() -> None:
        services.unregister(OutsideRecord)
        services.register(ActionJudge, Judge(Verdict("run", "asked_directly", "You asked for it.")))
        try:
            outside, _, _ = build(Fake(TOOLS))
            await after_read(outside)
            assert (await outside.call(asked("lamp"))).content == "ok"
            assert await outside.receipts() is None
            assert (await outside.call(asked("garage", "c2"))).content.startswith("ok")
            receipts = await outside.receipts()
            assert receipts is not None and [r.detail for r in receipts.done] == [CONFIG.unlabelled]
        finally:
            services.unregister(ActionJudge)
            services.register(OutsideRecord, MemoryRecord())

    run(go())


def test_a_failed_change_is_not_recorded_as_done() -> None:
    async def go() -> None:
        fake = Fake(TOOLS, {"lamp": ToolResult("x", "no", True)})
        outside, _, _ = build(fake)
        await after_read(outside)
        assert (await outside.call(asked("lamp"))).is_error
        assert await outside.receipts() is None

    run(go())


def test_a_change_outside_a_private_reply_is_recorded_by_its_label_alone() -> None:
    async def go() -> None:
        shared = Standing(HOUSEHOLD, SPEAKER, private=False, agreeing=False)
        outside, _, _ = build(Fake(TOOLS), standing=shared)
        await after_read(outside)
        await outside.call(asked("lamp", secret="the alarm code"))
        row = (await services.get(OutsideRecord).of_turn(CONVERSATION, TURN))[0]
        assert row.summary == CONFIG.unlabelled and row.tool == "lamp"

    run(go())


def test_the_inner_tool_sees_what_tainted_the_turn_and_an_untainted_turn_sees_none() -> None:
    seen: list[str | None] = []

    class Peeking(Fake):
        async def call(self, call: ToolCall) -> ToolResult:
            seen.append(tainted.current())
            return await super().call(call)

    async def go() -> None:
        outside, _, _ = build(Peeking(TOOLS))
        await outside.call(asked("lamp", "c0"))
        await outside.call(asked("look", "c1"))
        await outside.call(asked("lamp", "c2"))

    run(go())
    assert seen == [None, None, "look"] and tainted.current() is None


def test_the_tier_and_judge_lines_carry_names_and_enums_never_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        outside, _, _ = build(Fake(TOOLS))
        await after_read(outside)
        await outside.call(asked("lamp", note="hush-9931"))
        await outside.call(asked("garage", note="hush-9931"))

    run(go())
    seen = capsys.readouterr()
    out = seen.out + seen.err
    tier, judged = events(out, "outside.tier"), events(out, "outside.judged")
    assert [(t["tool"], t["tier"]) for t in tier] == [("lamp", "runs"), ("garage", "judged")]
    assert [(j["tool"], j["decision"], j["reason"]) for j in judged] == [("garage", "ask", "no_judge")]
    assert "hush-9931" not in out


def test_an_agreeing_tool_is_still_refused_whatever_its_tier() -> None:
    async def go() -> None:
        outside, fake, _ = build(Fake((*TOOLS, spec("confirm", agrees=True, tier="runs"))))
        await after_read(outside)
        assert (await outside.call(asked("confirm"))).is_error and [c.name for c in fake.ran] == ["look"]

    run(go())

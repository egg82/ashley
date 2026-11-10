"""What `Outside.receipts` shows beside her reply: the headline is the tool's label (else the shipped `unlabelled`, never
the tool's name), a shared reply shows no detail, a runs-tier change is never shown, a judged change whose record could
not be written still is, a turn resumed over the same record builds the same receipts, and the log carries counts only."""

import logging
from collections.abc import Generator, Mapping

import pytest
from ashley import services
from ashley.inference.model import ToolSpec
from ashley.senses.outside_record import OutsideRecord
from ashley.tools.action_judge import ActionJudge, Verdict
from ashley.tools.outside import Outside, Standing
from ashley.tools.outside_config import load
from outside_ask_support import CONVERSATION, HOUSEHOLD, SPEAKER, STANDING, TURN, Fake, asked, build, run, spec
from outside_record_support import MemoryRecord
from test_outside_explanations import Fixed

CONFIG = load()
LABELLED = ToolSpec("garage", "garage", {"type": "object"}, label="Opened the garage door")
TOOLS = (spec("look", reads=True, outside=True), LABELLED, spec("lamp", tier="runs"), spec("plain"))
SHARED = Standing(HOUSEHOLD, SPEAKER, private=False, agreeing=False)
WHY = "You asked me to open the garage SECRET-WHY."


@pytest.fixture(autouse=True)
def judge_says_run() -> Generator[None]:
    services.register(ActionJudge, Fixed(Verdict("run", "asked_directly", WHY)))
    yield
    services.unregister(ActionJudge)


def events(caplog: pytest.LogCaptureFixture, event: str) -> list[Mapping[str, object]]:
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == event]


async def after_read(outside: Outside) -> None:
    await outside.catalogue()
    await outside.call(asked("look", "r"))


def test_the_headline_is_the_tools_label_and_a_tool_with_none_gets_the_shipped_words_never_its_name() -> None:
    async def go() -> None:
        outside, _, _ = build(Fake(TOOLS))
        await after_read(outside)
        await outside.call(asked("garage", "a"))
        await outside.call(asked("plain", "b"))
        receipts = await outside.receipts()
        assert receipts is not None
        assert [r.headline for r in receipts.done] == ["Opened the garage door", CONFIG.unlabelled]
        assert all(r.headline != "plain" for r in receipts.done)
        assert [r.why for r in receipts.done] == [WHY, WHY]

    run(go())


def test_a_held_call_is_headed_by_its_label_and_shows_the_code_summary_in_full() -> None:
    async def go() -> None:
        services.unregister(ActionJudge)
        outside, _, _ = build(Fake(TOOLS))
        await after_read(outside)
        await outside.call(asked("garage", "a", door="left"))
        await outside.call(asked("plain", "b"))
        receipts = await outside.receipts()
        assert receipts is not None and receipts.done == () and receipts.proposal_id == outside.agree
        assert [(h.headline, h.detail) for h in receipts.held] == [
            ("Opened the garage door", 'Opened the garage door (door: "left")'), (CONFIG.unlabelled, CONFIG.unlabelled)]

    run(go())


def test_a_shared_reply_shows_the_label_and_no_detail() -> None:
    async def go() -> None:
        outside, _, _ = build(Fake(TOOLS), standing=SHARED)
        await after_read(outside)
        assert not (await outside.call(asked("garage", "a", door="left"))).is_error
        receipts = await outside.receipts()
        assert receipts is not None and [(r.headline, r.detail) for r in receipts.done] == [("Opened the garage door", None)]

    run(go())


def test_a_runs_tier_change_is_recorded_and_never_shown() -> None:
    async def go() -> None:
        outside, _, _ = build(Fake(TOOLS))
        await after_read(outside)
        await outside.call(asked("lamp", "a"))
        record = services.get(OutsideRecord)
        assert isinstance(record, MemoryRecord) and [a.tier for a in record.actions] == ["runs"]
        assert await outside.receipts() is None

    run(go())


def test_a_judged_change_whose_record_could_not_be_written_is_still_shown() -> None:
    async def go() -> None:
        services.unregister(OutsideRecord)
        outside, _, _ = build(Fake(TOOLS))
        await after_read(outside)
        await outside.call(asked("garage", "a"))
        receipts = await outside.receipts()
        assert receipts is not None and [(r.headline, r.why) for r in receipts.done] == [("Opened the garage door", WHY)]
        services.register(OutsideRecord, MemoryRecord())

    run(go())


def test_the_record_keeps_the_headline_the_change_was_shown_under() -> None:
    async def go() -> None:
        outside, _, _ = build(Fake(TOOLS))
        await after_read(outside)
        await outside.call(asked("garage", "a"))
        await outside.call(asked("plain", "b"))
        rows = await services.get(OutsideRecord).of_turn(CONVERSATION, TURN)
        assert [r.label for r in rows] == ["Opened the garage door", CONFIG.unlabelled]

    run(go())


def test_a_turn_resumed_over_the_same_record_builds_the_same_receipts() -> None:
    async def go() -> None:
        first, _, _ = build(Fake(TOOLS))
        await after_read(first)
        await first.call(asked("garage", "a"))
        again = Outside(Fake(TOOLS), STANDING, (CONVERSATION, TURN), tainted="look")
        assert await again.receipts() == await first.receipts() is not None

    run(go())


def test_the_log_carries_counts_and_never_a_label_a_summary_or_a_reason(caplog: pytest.LogCaptureFixture) -> None:
    async def go() -> None:
        caplog.set_level(logging.INFO)
        outside, _, _ = build(Fake(TOOLS))
        await after_read(outside)
        await outside.call(asked("garage", "a", door="PLANTED-SUMMARY"))
        await outside.receipts()
        [line] = events(caplog, "outside.receipts")
        assert line["done"] == 1 and line["held"] == 0 and line["conversation"] == CONVERSATION
        everything = repr([r.__dict__ for r in caplog.records])
        assert "SECRET-WHY" not in everything and "Opened the garage door" not in everything
        assert "PLANTED-SUMMARY" not in everything

    run(go())

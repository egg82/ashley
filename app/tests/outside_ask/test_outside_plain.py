"""A receipt names a change in plain words and never by its tool: the detail of a change that ran and of a held call is the
tool's label with its arguments, and the stored record holds the same."""

from collections.abc import Generator

import pytest
from ashley import services
from ashley.inference.model import ToolSpec
from ashley.senses.outside_record import OutsideRecord
from ashley.tools.action_judge import ActionJudge, Verdict
from outside_ask_support import CONVERSATION, TURN, Fake, asked, build, run, spec
from outside_record_support import MemoryRecord
from test_outside_explanations import Fixed

LABEL = "Moved an email to a folder"
MOVE = ToolSpec("mail_label", "move mail", {"type": "object"}, label=LABEL)
TOOLS = (spec("look", reads=True, outside=True), MOVE)


@pytest.fixture(autouse=True)
def judge_says_run() -> Generator[None]:
    services.register(ActionJudge, Fixed(Verdict("run", "asked_directly", "You asked for it.")))
    services.register(OutsideRecord, MemoryRecord())
    yield
    services.unregister(ActionJudge)
    services.unregister(OutsideRecord)


async def ran(outside: object) -> None:
    from ashley.tools.outside import Outside
    assert isinstance(outside, Outside)
    await outside.catalogue()
    await outside.call(asked("look", "r"))
    await outside.call(asked("mail_label", "m", folder="archive", subject="a subject line"))


def test_a_change_that_ran_is_shown_as_its_label_and_the_folder_it_names() -> None:
    async def go() -> None:
        outside, _, _ = build(Fake(TOOLS))
        await ran(outside)
        receipts = await outside.receipts()
        assert receipts is not None and [(r.headline, r.detail) for r in receipts.done] == [
            (LABEL, f"{LABEL} (folder: archive)")]

    run(go())


def test_the_stored_record_holds_the_same_words_and_no_tool_name() -> None:
    async def go() -> None:
        outside, _, _ = build(Fake(TOOLS))
        await ran(outside)
        row = (await services.get(OutsideRecord).of_turn(CONVERSATION, TURN))[0]
        assert row.tool == "mail_label" and row.summary == f"{LABEL} (folder: archive)" and "mail_label" not in row.summary

    run(go())


def test_a_held_call_shows_its_label_and_every_argument_and_no_tool_name() -> None:
    async def go() -> None:
        services.unregister(ActionJudge)
        outside, _, _ = build(Fake(TOOLS))
        await ran(outside)
        receipts = await outside.receipts()
        assert receipts is not None and [h.detail for h in receipts.held] == [
            f'{LABEL} (folder: "archive", subject: "a subject line")']
        assert "mail_label" not in repr(receipts)

    run(go())


def test_a_held_call_keeps_its_label_when_the_page_moves_and_the_tool_is_no_longer_offered() -> None:
    async def go() -> None:
        services.unregister(ActionJudge)
        outside, fake, _ = build(Fake(TOOLS))
        await ran(outside)
        fake.specs = tuple(s for s in TOOLS if s.name != "mail_label")
        await outside.catalogue()
        receipts = await outside.receipts()
        assert receipts is not None and [h.headline for h in receipts.held] == [LABEL]

    run(go())

"""Contract 12: a carried turn of hers that had receipts gets the configured history line on a line of its own after her
words, and `said_before` likewise; a turn without gets nothing. Her stored words stay hers."""

import asyncio
from datetime import UTC, datetime

from ashley.channels.prompt import messages, said_before
from ashley.channels.respond import respond
from ashley.conversations.model import Receipt, Receipts, Turn
from ashley.inference.model import Message
from ashley.tools import outside_config
from contract.conversations_support import run
from receipts_blind_support import (ANSWER, CHECKING, LAMP_LABEL, OKAY, World, change, database, fixed_part, hers,
                                    looked, play, settled)
from respond_support import ALANA, HOME

AT = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)
RECEIPTS = Receipts((Receipt("RB-did-lamp", "house_do (action: light.turn_on)", "RB-because"),),
                    (Receipt("RB-held-mail", 'mail_label (folder: "archive")', None),), 12)
ASKED = Turn(2, "person", ALANA.id, "and the other thing?", AT)


def hers_with(receipts: Receipts | None) -> Turn:
    return Turn(1, "ashley", None, OKAY, AT, answers=0, receipts=receipts)


def test_c12_a_carried_turn_with_receipts_has_the_history_line_alone_on_a_line_after_her_words() -> None:
    (earlier, _) = messages([hers_with(RECEIPTS)], ASKED, HOME)
    lines = earlier.text.split("\n")
    assert len(lines) == 2 and lines[0].endswith(f") {OKAY}")
    assert fixed_part(outside_config.load().history_line) in lines[1]
    assert "RB-did-lamp" in lines[1] and "RB-held-mail" in lines[1]
    assert 'mail_label (folder: "archive")' in lines[1], "a held call is named with its summary"


def test_c12_a_done_only_turn_names_its_headlines_and_no_waiting_part() -> None:
    done = Receipts(RECEIPTS.done, (), None)
    (earlier, _) = messages([hers_with(done)], ASKED, HOME)
    line = earlier.text.split("\n")[1]
    assert "RB-did-lamp" in line and "RB-held-mail" not in line


def test_c12_a_carried_turn_without_receipts_gets_nothing() -> None:
    (earlier, _) = messages([hers_with(None)], ASKED, HOME)
    assert "\n" not in earlier.text and earlier.text.endswith(f") {OKAY}")


def test_c12_said_before_carries_the_line_likewise() -> None:
    (with_line,) = said_before([hers_with(RECEIPTS)], HOME)
    (without,) = said_before([hers_with(None)], HOME)
    assert without.endswith(f"You: {OKAY}") and "\n" not in without
    first, second = with_line.split("\n")
    assert first == without and fixed_part(outside_config.load().history_line) in second and "RB-did-lamp" in second


def test_c12_the_next_prompt_carries_the_line_while_her_stored_words_stay_hers(world: World) -> None:
    async def go() -> None:
        async with database(world):
            first = await play(world, world.web(), [CHECKING, looked(), change(), ANSWER])
            world.first.model.script = [ANSWER]
            await respond(world.web("and again"))
            await settled(first.conversation_id, 3)
            carried = [m for m in world.first.model.prompts[-1].messages if isinstance(m, Message)
                       and m.author == "ashley" and OKAY in m.text]
            assert carried and LAMP_LABEL in carried[0].text and carried[0].text.count("\n") == 1
            assert all(t.text in (OKAY, CHECKING.text) for t in await hers(first.conversation_id))
            await asyncio.sleep(0.05)

    run(go())

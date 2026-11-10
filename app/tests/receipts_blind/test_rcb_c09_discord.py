"""Contract 9, Discord: her chunks are as they were; when the turn has receipts exactly one more message follows them,
every line of it Discord subtext, outside `max_messages`; none otherwise; the same from the outbox."""

from collections.abc import Coroutine
from typing import Any

import pytest
from ashley.channels.discord import receipt_lines
from ashley.channels.discord.chunks import chunks
from ashley.channels.model import Outbound
from ashley.conversations.model import Receipt, Receipts
from contract.conversations_support import run
from receipts_blind_discord_support import answered, config, post_later
from receipts_blind_support import ANSWER, CHECKING, OKAY, World, change, database, looked, play

DONE = Receipts((Receipt("RB-did-lamp", "house_do (action: light.turn_on)", "RB-because"),), (), None)
HELD = Receipts((), (Receipt("RB-held-mail", 'mail_label (folder: "archive", subject: "RB-subject")', None),
                     Receipt("RB-held-lamp", "house_do (action: light.turn_on)", "RB-asked")), 9)
BOTH = Receipts(DONE.done, HELD.held, 9)
LONG = " ".join(f"word{n}" for n in range(1500))


def outbound(body: str, receipts: Receipts | None) -> Outbound:
    return Outbound(77, "text", body, receipts=receipts)


def test_c09_her_words_then_exactly_one_subtext_message_after_them() -> None:
    texts = run_one(answered(outbound("Okay.", DONE)))
    assert texts[0] == "Okay." and len(texts) == 2
    assert all(line.startswith("-# ") for line in texts[1].splitlines())
    assert "RB-did-lamp" in texts[1]


def test_c09_a_turn_without_receipts_sends_only_her_words() -> None:
    assert run_one(answered(outbound("Okay.", None))) == ["Okay."]


def test_c09_her_chunks_are_as_they_were_and_the_extra_message_is_outside_max_messages() -> None:
    texts = run_one(answered(outbound(LONG, DONE), max_messages=2))
    assert texts[:2] == chunks(LONG, 2000, 2) and len(texts) == 3
    assert texts[2].startswith("-# ")


def test_c09_held_calls_show_their_full_summary_and_end_with_the_footer() -> None:
    texts = run_one(answered(outbound("Okay.", HELD)))
    lines = texts[1].splitlines()
    assert 'mail_label (folder: "archive", subject: "RB-subject")' in texts[1] and "RB-asked" in texts[1]
    assert all(line.startswith("-# ") for line in lines)
    assert config.held_footer in lines[-1]


def test_c09_a_done_only_message_has_no_footer() -> None:
    assert config.held_footer not in run_one(answered(outbound("Okay.", DONE)))[1]


def test_c09_done_lines_come_before_held_lines() -> None:
    text = run_one(answered(outbound("Okay.", BOTH)))[1]
    assert text.index("RB-did-lamp") < text.index("RB-held-mail") < text.index(config.held_footer)


def test_c09_every_line_is_subtext_even_when_a_detail_runs_over_lines() -> None:
    wrapped = Receipts((Receipt("RB-did\nsecond line of a headline", "first\nsecond", "why\n\nmore"),), (), None)
    text = receipt_lines(wrapped, config)
    assert text is not None and all(line.startswith("-# ") for line in text.splitlines() if line)
    assert "" not in text.splitlines(), "a blank line would end the subtext"


def test_c09_no_receipts_is_no_message_and_receipts_are_one_string() -> None:
    assert receipt_lines(None, config) is None
    got = receipt_lines(DONE, config)
    assert isinstance(got, str) and got.startswith("-# ")


@pytest.mark.parametrize("receipts", [DONE, HELD, None])
def test_c09_the_outbox_posts_her_chunks_then_the_receipt_message_or_nothing_more(receipts: Receipts | None) -> None:
    texts = run_one(post_later(outbound(LONG, receipts), max_messages=2))
    assert texts[:2] == chunks(LONG, 2000, 2)
    assert len(texts) == (2 if receipts is None else 3)
    if receipts is not None:
        assert all(line.startswith("-# ") for line in texts[2].splitlines())


def run_one(work: Coroutine[Any, Any, list[str]]) -> list[str]:
    got: list[list[str]] = []

    async def go() -> None:
        got.append(await work)

    run(go())
    return got[0]


def test_c09_the_outbox_row_for_a_discord_thread_carries_the_receipts_beside_her_words(world: World) -> None:
    async def go() -> None:
        async with database(world):
            played = await play(world, world.discord(), [CHECKING, looked(), change(), ANSWER])
            (row,) = [r for r in played.queued if r.thread.startswith("discord:")]
            assert row.outbound.body == OKAY and row.outbound.receipts == played.answer.receipts
            assert row.outbound.receipts is not None and len(played.queued) == 1

    run(go())

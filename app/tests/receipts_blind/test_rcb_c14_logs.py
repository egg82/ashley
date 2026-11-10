"""Contract 14: `outside.receipts` and `receipts.unshown` carry ids and counts only. A planted label, summary, why and
argument never appears in any log record of a turn that has them, on a page, in Discord or by voice."""

import pytest
from contract.conversations_support import run
from later_support import Logged
from receipts_blind_support import (ANSWER, CHECKING, LAMP_LABEL, MAIL_LABEL, ROOM_PLANT, WHY_ASKED, WHY_RAN, World,
                                    changes, database, looked, play)

PLANTS = [LAMP_LABEL, MAIL_LABEL, ROOM_PLANT, WHY_RAN, WHY_ASKED, "RB-LABEL", "light.turn_on", "house_do (", "mail_label ("]


def check(log: Logged, done: str, held: str) -> None:
    text = log.read()
    lines = log.events("outside.receipts")
    assert lines and all(set(line) >= {"conversation", "turn", "done", "held"} for line in lines)
    assert any((line["done"], line["held"]) == (done, held) for line in lines)
    assert "outside.receipts" in text, "the probe saw the log"
    assert [p for p in PLANTS if p in text] == []


@pytest.mark.parametrize("channel", ["web", "discord", "voice"])
def test_c14_no_planted_label_summary_why_or_argument_reaches_a_log(
        world: World, capsys: pytest.CaptureFixture[str], channel: str) -> None:
    world.judge.answers = {"mail_label": "ask"}
    log = Logged(capsys)
    later = channel != "voice"
    inbound = {"web": world.web, "discord": world.discord, "voice": world.voice}[channel]()
    script = [CHECKING, looked(), changes("house_do", "mail_label"), ANSWER] if later else [
        looked(), changes("house_do", "mail_label"), ANSWER]

    async def go() -> None:
        async with database(world):
            played = await play(world, inbound, script)
            assert played.answer.receipts is not None

    run(go())
    check(log, "1", "1")


def test_c14_the_unshown_line_names_counts_only(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)

    async def go() -> None:
        async with database(world):
            await play(world, world.voice(), [looked(), changes("house_do"), ANSWER])

    run(go())
    (line,) = log.events("receipts.unshown")
    assert set(line) >= {"conversation", "medium", "done", "held"}
    assert [p for p in PLANTS if p in log.read()] == []

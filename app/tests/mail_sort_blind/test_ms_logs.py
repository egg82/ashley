"""The sort's logs carry no brief, address or subject (design, Logs: "None carries an address, a subject, a body ..."; "a
watch gains `brief` ... people's data, never logged"). Each test has a control: a line the code owns is in the output, so
an empty capture cannot pass."""

import asyncio

import pytest
from ashley import logs
from ashley.watches.model import ReadFailed
from contract.conversations_support import events
from mail_sort_blind_arming_support import arming, sort_args, use
from mail_sort_blind_support import BRIEF, ITEMS, MORE, Store, run, scenario
from mail_sort_blind_turn_support import M1, Rig, entry, held, sort_watch, with_rig, woken

MARKS = ("zs-brief-6643", "zs-box-5512", "zs-other-8830", "Invoice", "bob@shop.test")


def test_the_store_and_the_job_log_neither_the_brief_nor_the_address(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def body(s: Store) -> None:
        a = await s.armed(hours=6.0, standing=True, brief=BRIEF)
        for answer in (ITEMS, MORE, ReadFailed("unreachable")):
            s.age(a, 1.0)
            await s.tick(answer)

    scenario(db_url, body)
    seen = capsys.readouterr()
    out = seen.out + seen.err
    assert events(out, "watches.tick") and events(out, "watches.woke")
    assert all(m not in out for m in MARKS), [m for m in MARKS if m in out]


def test_arming_and_agreeing_log_neither_the_brief_nor_the_address(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with arming() as w:
            await use(w.watch(10), "watch", sort_args(brief=BRIEF))
            await use(w.reminders(11), "arm_reminder")

    asyncio.run(go())
    seen = capsys.readouterr()
    out = seen.out + seen.err
    assert events(out, "watches.armed")
    assert all(m not in out for m in MARKS), [m for m in MARKS if m in out]


def test_the_woken_turn_logs_neither_the_brief_nor_the_address_nor_the_subject(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def body(rig: Rig) -> None:
        turn = rig.turn(woken(sort_watch()))
        assert not held(await turn.label(M1, add=["School"]))
        assert held(await turn.label(entry("m2", "Bob <bob@shop.test>", "Invoice"), folder="trash"))
        await turn.ends()

    run(with_rig(body))
    seen = capsys.readouterr()
    out = seen.out + seen.err
    assert events(out, "outside.held") and events(out, "outside.tier")
    assert all(m not in out for m in MARKS), [m for m in MARKS if m in out]

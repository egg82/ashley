"""The recipient check is code, before the judge (design 4.3): a recipient that is not known is held with no judge call;
a household address, an address this mailbox has sent to, or an exact address in the person's words passes to the judge."""

import logging

import pytest
from action_judge_blind_support import (FORM, KNOWN, SAM_ADDRESS, SENT_BEFORE, STRANGER, UNKNOWN_RECIPIENT, Judged,
                                        mail, run_judged, says, sends)
from ashley.inference.model import ToolCall
from mail_gmail_support import ADDRESS, message, part
from taint_tiers_blind.taint_tiers_blind_support import PLANT


def mail_to(*to: str) -> ToolCall:
    return ToolCall("m1", "mail_send", {**FORM, "to": list(to)})


async def sent(j: Judged, words: str, *to: str, sent_to: tuple[str, ...] = ()) -> tuple[bool, int, bool]:
    """(the message went out, judge calls, held) for a tainted turn that said `words` and sends to `to`."""
    tools, gmail = mail(sent_to)
    o = j.outside(tools, words=words)
    await o.catalogue()
    await o.call(mail_to(*to))
    return bool(sends(gmail)), j.calls, bool(await j.held())


def test_an_unknown_recipient_is_held_and_the_judge_is_not_called(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def body(j: Judged) -> None:
        caplog.set_level(logging.INFO)
        assert await sent(j, "send the form to the school", STRANGER) == (False, 0, True)
        reasons = {dict(getattr(r, "fields", {})).get("reason") for r in caplog.records}
        assert reasons & UNKNOWN_RECIPIENT, reasons

    run_judged(db_url, body, [says("run")])


def test_one_unknown_recipient_among_known_ones_holds_the_whole_call(db_url: str) -> None:
    async def body(j: Judged) -> None:
        assert await sent(j, f"email {KNOWN}", KNOWN, STRANGER, sent_to=(KNOWN,)) == (False, 0, True)

    run_judged(db_url, body, [says("run")])


def test_a_household_address_goes_to_the_judge(db_url: str) -> None:
    async def body(j: Judged) -> None:
        assert await sent(j, "send Sam the form", SAM_ADDRESS) == (True, 1, False)

    run_judged(db_url, body, [says("run")])


def test_an_address_this_mailbox_sent_to_before_goes_to_the_judge_after_one_query(db_url: str) -> None:
    async def body(j: Judged) -> None:
        tools, gmail = mail((SENT_BEFORE,))
        o = j.outside(tools, words="send the coach the form")
        await o.catalogue()
        await o.call(mail_to(SENT_BEFORE))
        assert sends(gmail) == ["/messages/send"] and j.calls == 1
        assert len(gmail.sent_queries()) == 1 and SENT_BEFORE in gmail.sent_queries()[0]

    run_judged(db_url, body, [says("run")])


def test_an_exact_address_in_the_persons_words_goes_to_the_judge(db_url: str) -> None:
    async def body(j: Judged) -> None:
        assert await sent(j, f"email {STRANGER} the form", STRANGER) == (True, 1, False)

    run_judged(db_url, body, [says("run")])


def test_an_address_the_person_only_described_is_not_known(db_url: str) -> None:
    async def body(j: Judged) -> None:
        assert await sent(j, "email mallory at evil dot test", STRANGER) == (False, 0, True)

    run_judged(db_url, body, [says("run")])


def test_an_address_in_a_read_mail_or_in_her_reply_does_not_make_it_known(db_url: str) -> None:
    async def body(j: Judged) -> None:
        tools, gmail = mail()
        gmail.messages[:] = [message("a1", "Hi", 1_762_000_000_000, body=part("text/plain", f"reply to {STRANGER} {PLANT}"))]
        o = j.outside(tools, words="reply to that email", earlier=(("ashley", f"They wrote from {STRANGER}"),))
        await o.catalogue()
        await o.call(ToolCall("r1", "mail_read", {"mailbox": ADDRESS, "id": "a1"}))
        await o.call(mail_to(STRANGER))
        assert sends(gmail) == [] and j.calls == 0 and len(await j.held()) == 1

    run_judged(db_url, body, [says("run")])


def test_a_known_recipient_still_needs_the_judge_to_say_run(db_url: str) -> None:
    async def body(j: Judged) -> None:
        assert await sent(j, "send Sam the form", SAM_ADDRESS) == (False, 1, True)

    run_judged(db_url, body, [says("ask", "not_asked")])

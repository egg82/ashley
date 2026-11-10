"""Logs: the kind logs through the `watches.*` lines, and none carries an address, a subject, a sender or a label."""

import pytest
from ashley import logs
from contract.conversations_support import events
from ashley.mail.model import MailFailed
from mail_inbox_blind_support import ADDRESS, LABEL, SENDER, SUBJECT, World, baseline_of, mail_watch, msg, run

SECRETS = (ADDRESS, SENDER, SUBJECT, LABEL, "zq-box-4471", "zq-sender-2290")


def logged(w: World, *watches: object, capsys: pytest.CaptureFixture[str]) -> str:
    logs.setup()
    run(w.tick(*watches))
    seen = capsys.readouterr()
    return seen.out + seen.err


def test_a_wake_logs_counts_and_never_what_the_mail_says(capsys: pytest.CaptureFixture[str]) -> None:
    w = World()
    w.inbox(msg(1, labels=(LABEL,)), msg(2, labels=(LABEL,)))
    out = logged(w, mail_watch(1, baseline=baseline_of(msg(1, labels=(LABEL,)))), capsys=capsys)
    [line] = events(out, "watches.woke")
    assert (line["new"], line["changed"], line["gone"]) == ("1", "0", "0")
    assert all(s not in out for s in SECRETS)


def test_a_baseline_a_quiet_read_and_a_syncing_one_log_nothing_the_mail_says(capsys: pytest.CaptureFixture[str]) -> None:
    w = World()
    w.inbox(msg(1, labels=(LABEL,)))
    out = logged(w, mail_watch(1, baseline=None), mail_watch(2, baseline=baseline_of(msg(1, labels=(LABEL,)))),
                 capsys=capsys)
    w.mailbox.syncing.add(11)
    out += logged(w, mail_watch(3, baseline=None), capsys=capsys)
    assert events(out, "watches.tick") and all(s not in out for s in SECRETS)


def test_a_failed_read_logs_its_reason_and_never_the_mailbox(capsys: pytest.CaptureFixture[str]) -> None:
    w = World()
    w.inbox(msg(1))
    w.mailbox.fail[11] = MailFailed("unreachable")
    out = logged(w, mail_watch(1, baseline=None), capsys=capsys)
    [line] = events(out, "watches.read_failed")
    assert (line["kind"], line["reason"], line["watches"]) == ("mail_inbox", "unreachable", "1")
    assert all(s not in out for s in SECRETS)

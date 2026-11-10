"""The `mail_inbox` kind against a scripted Mailbox: what it reads and keys, who may be read for, how each mailbox
answer maps to a read, and that a `syncing` answer is `Later` through the judge and the job, never every message gone."""

import asyncio
import logging
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from ashley import services
from ashley.logs import Logfmt
from ashley.mail.mailbox import Mailbox, NullMailbox
from ashley.mail.model import Account, Header, MailFailed, MailQuery, Page, Reason
from ashley.watches import job
from ashley.watches.arming import Seen, look
from ashley.watches.config import CONFIG
from ashley.watches.diff import Items
from ashley.watches.judge import judge
from ashley.watches.kinds import Registry
from ashley.watches.mail_inbox import MailInbox, items_of
from ashley.watches.model import Baseline, FailReason, Later, Quiet, Read, ReadFailed, Watch, Woke
from ashley.watches.watches import Watches
from mail_gmail_support import ADDRESS, ALANA, SAM, connect
from watch_job_support import FakeWatches, ScriptedKind, watch

MAIL = CONFIG.kinds["mail_inbox"]
NOW = datetime(2026, 11, 6, 18, 30, tzinfo=UTC)


def header(id_: str, subject: str = "Hi", labels: tuple[str, ...] = (), unread: bool = True) -> Header:
    return Header(id_, f"{id_}@x.test", ADDRESS, subject, NOW, "", labels, "inbox", unread, 0)


class ScriptedMailbox(NullMailbox):
    """Answers `pages` in turn (a cursor on all but the last), or raises `fail`; remembers each account and query."""

    def __init__(self, pages: tuple[tuple[Header, ...], ...] = ((),), fail: Reason | None = None, read: bool = True) -> None:
        self.pages = pages
        self.fail: Reason | None = fail
        self.readable = read
        self.asked: list[tuple[Account, MailQuery]] = []

    def can_read(self, kind: str, scopes: tuple[str, ...]) -> bool:
        return self.readable

    async def search(self, account: Account, query: MailQuery) -> Page[Header]:
        self.asked.append((account, query))
        if self.fail is not None:
            raise MailFailed(self.fail)
        n = len(self.asked)
        return Page(self.pages[n - 1], n < len(self.pages), str(n) if n < len(self.pages) else "")


def inbox_watch(watch_id: int = 1, person: int = ALANA, target: str = ADDRESS, baseline: Items | None = None) -> Watch:
    base = watch(watch_id, kind="mail_inbox", target=target, person=person, when=MAIL.when)
    return replace(base, track=MAIL.track, baseline=baseline)


def read(mailbox: ScriptedMailbox, *group: Watch) -> dict[int, Read]:
    services.register(Mailbox, mailbox)
    return dict(asyncio.run(MailInbox().read(group or (inbox_watch(),))))


def test_each_message_is_an_item_keyed_by_id_tracking_from_subject_unread_and_sorted_labels() -> None:
    connect()
    got = read(ScriptedMailbox(((header("m1", "Trip", ("b", "a"), True), header("m2", unread=False)),)))
    assert got[1] == {"m1": {"from": "m1@x.test", "subject": "Trip", "unread": True, "labels": "a,b"},
                      "m2": {"from": "m2@x.test", "subject": "Hi", "unread": False, "labels": ""}}


def test_it_asks_for_the_inbox_folder_as_the_connections_account() -> None:
    connect()
    box = ScriptedMailbox()
    read(box)
    assert box.asked == [(Account(1, 1, ALANA, "google", ADDRESS), MailQuery(folder="inbox"))]


def test_it_pages_to_max_items_and_no_further() -> None:
    connect()
    first = tuple(header(f"a{i}") for i in range(30))
    second = tuple(header(f"b{i}") for i in range(30))
    box = ScriptedMailbox((first, second, (header("never"),)))
    got = read(box)[1]
    assert isinstance(got, dict) and len(got) == CONFIG.max_items and "never" not in got and "b19" in got
    assert [q.page for _, q in box.asked] == ["", "1"]


def test_the_boundary_of_who_may_be_read_for_is_the_resource_gate() -> None:
    connect(person=SAM)
    assert read(ScriptedMailbox(), inbox_watch(person=ALANA))[1] == ReadFailed("not_connected")
    assert isinstance(read(ScriptedMailbox(), inbox_watch(person=SAM))[1], dict)
    connect(person=ALANA, shared=True)
    assert isinstance(read(ScriptedMailbox(), inbox_watch(person=ALANA))[1], dict)


def test_an_unknown_address_a_connection_that_needs_connecting_and_a_missing_scope_each_fail_by_name() -> None:
    connect()
    assert read(ScriptedMailbox(), inbox_watch(target="other@x.test"))[1] == ReadFailed("not_connected")
    assert read(ScriptedMailbox(read=False))[1] == ReadFailed("refused")


def test_the_target_address_matches_the_mailbox_whatever_its_case() -> None:
    connect()
    assert isinstance(read(ScriptedMailbox(), inbox_watch(target=ADDRESS.upper()))[1], dict)


def test_a_connection_that_needs_connecting_is_not_read() -> None:
    connect(needs="reconnect")
    box = ScriptedMailbox()
    assert read(box)[1] == ReadFailed("not_connected") and box.asked == []


@pytest.mark.parametrize(("reason", "failed"), [("refused", "refused"), ("unreachable", "unreachable"),
                                                  ("needs_reconnect", "not_connected"), ("not_found", "bad_result")])
def test_a_mailbox_failure_is_a_failed_read_by_its_reason(reason: Reason, failed: FailReason) -> None:
    connect()
    assert read(ScriptedMailbox(fail=reason))[1] == ReadFailed(failed)


def test_syncing_reads_later_not_an_empty_inbox() -> None:
    connect()
    got = read(ScriptedMailbox(fail="syncing"))[1]
    assert got == Later() and got != {}


def test_one_watchs_syncing_mailbox_does_not_fail_the_other_in_the_group() -> None:
    connect()
    got = read(ScriptedMailbox(((header("m1"),),)), inbox_watch(1), inbox_watch(2, target="gone@x.test"))
    assert isinstance(got[1], dict) and got[2] == ReadFailed("not_connected")


def test_a_later_read_is_the_later_check_whatever_the_baseline() -> None:
    held = items_of((header("m1"),))
    assert judge(Later(), inbox_watch(baseline=None)) == Later()
    assert judge(Later(), inbox_watch(baseline=held)) == Later()
    gone = judge({}, replace(inbox_watch(baseline=held), when=MAIL.handoff_until))
    assert isinstance(gone, Woke) and [c.kind for c in gone.changes] == ["gone"]


def test_a_new_message_wakes_and_a_label_read_or_subject_change_does_not() -> None:
    before = items_of((header("m1", "Trip", (), True),))
    w = inbox_watch(baseline=before)
    assert isinstance(judge(items_of((header("m1", "Trip", ("School",), True),)), w), Quiet)
    assert isinstance(judge(items_of((header("m1", "Trip", (), False),)), w), Quiet)
    assert isinstance(judge(items_of((header("m1", "Trip!", (), True),)), w), Quiet)
    assert isinstance(judge({}, w), Quiet)
    woke = judge(items_of((header("m2"), header("m1", "Trip", (), True))), w)
    assert isinstance(woke, Woke) and [(c.id, c.kind) for c in woke.changes] == [("m2", "new")]
    assert isinstance(judge(items_of((header("m1", "Trip", (), True),)), replace(w, baseline=None)), Baseline)


def test_the_kind_is_outside_tracks_the_four_fields_and_defaults_to_new() -> None:
    assert MailInbox().outside is True
    assert MAIL.track == ("from", "subject", "unread", "labels")
    assert [(p.kind, p.negate) for alt in MAIL.when for p in alt] == [("new", False)]


def test_a_later_tick_records_later_without_a_failure_and_logs_no_content(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    store = FakeWatches(due_rows=(inbox_watch(1, baseline=items_of((header("m1", "secret subject"),))),))
    services.register(Watches, store)
    counts: Counter[str] = asyncio.run(job.tick(CONFIG, Registry([ScriptedKind(name="mail_inbox", reads={1: Later()})])))
    assert [c for _, _, c in store.recorded] == [Later()]
    assert (counts["later"], counts["failed"], counts["paused"], counts["quiet"], counts["woke"]) == (1, 0, 0, 0, 0)
    text = "\n".join(Logfmt().format(r) for r in caplog.records)
    assert "event=watches.tick" in text and "later=1" in text and "read_failed" not in text and "secret" not in text


def test_arming_over_an_empty_inbox_sees_the_mailbox_with_no_items() -> None:
    connect()
    services.register(Mailbox, ScriptedMailbox())
    seen = asyncio.run(look(1, ALANA, "mail_inbox", ADDRESS, NOW))
    assert isinstance(seen, Seen) and seen.items == {}
    services.register(Mailbox, ScriptedMailbox(((header("m1"),),)))
    full = asyncio.run(look(1, ALANA, "mail_inbox", ADDRESS, NOW))
    assert isinstance(full, Seen) and set(full.items) == {"m1"}


def test_arming_over_a_syncing_mailbox_is_unreachable_not_missing() -> None:
    connect()
    services.register(Mailbox, ScriptedMailbox(fail="syncing"))
    assert asyncio.run(look(1, ALANA, "mail_inbox", ADDRESS, NOW)) == ReadFailed("unreachable")

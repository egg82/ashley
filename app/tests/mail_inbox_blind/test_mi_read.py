"""A read: the newest `max_items` inbox messages as items keyed by message id, tracking from, subject, unread and labels,
read per watch from the watch's own mailbox."""

from ashley.mail.model import MailFailed, Reason
from ashley.watches.model import Baseline, Failed
from mail_inbox_blind_support import (ADDRESS, CONFIG, LABEL, OTHER_ADDRESS, SENDER, SUBJECT, FakeResources, World,
                                      labels_of, mail_watch, msg, run)


def items_of(check: object) -> dict[str, dict[str, object]]:
    assert isinstance(check, Baseline), check
    return {k: dict(v) for k, v in check.items.items()}


def test_the_first_read_is_a_baseline_of_items_keyed_by_message_id_with_the_four_fields() -> None:
    w = World()
    w.inbox(msg(1, unread=True, labels=(LABEL,)), msg(2, unread=False, subject="plain"))

    async def go() -> None:
        got = items_of(await w.check(mail_watch(1, baseline=None)))
        assert set(got) == {"m0001", "m0002"}
        first, second = got["m0001"], got["m0002"]
        assert set(first) == {"from", "subject", "unread", "labels"} == set(second)
        assert (first["from"], first["subject"], first["unread"]) == (SENDER, f"{SUBJECT}-1", True)
        assert labels_of(first["labels"]) == {LABEL} and labels_of(second["labels"]) == set()
        assert (second["subject"], second["unread"]) == ("plain", False)
    run(go())


def test_the_read_is_the_newest_max_items_even_when_the_port_answers_in_smaller_pages() -> None:
    w = World()
    total = CONFIG.max_items + 7
    w.inbox(*[msg(n) for n in range(1, total + 1)])

    async def go() -> None:
        got = items_of(await w.check(mail_watch(1, baseline=None)))
        assert set(got) == {f"m{n:04d}" for n in range(total - CONFIG.max_items + 1, total + 1)}
    run(go())


def test_only_the_inbox_is_read() -> None:
    w = World()
    w.inbox(msg(1), msg(2, folder="sent"), msg(3, folder="trash"), msg(4, folder=""), msg(5))

    async def go() -> None:
        assert set(items_of(await w.check(mail_watch(1, baseline=None)))) == {"m0001", "m0005"}
    run(go())


def test_the_window_is_the_newest_inbox_messages_not_the_newest_of_every_folder() -> None:
    w = World()
    w.inbox(*[msg(n) for n in range(1, CONFIG.max_items + 1)], *[msg(n, folder="sent") for n in range(100, 110)])

    async def go() -> None:
        got = items_of(await w.check(mail_watch(1, baseline=None)))
        assert set(got) == {f"m{n:04d}" for n in range(1, CONFIG.max_items + 1)}
    run(go())


def test_an_empty_inbox_reads_as_no_items_not_as_a_failure() -> None:
    w = World()
    w.inbox()

    async def go() -> None:
        assert items_of(await w.check(mail_watch(1, baseline=None))) == {}
    run(go())


def test_a_subject_longer_than_a_tracked_value_is_cut_to_max_value_chars() -> None:
    w = World()
    w.inbox(msg(1, subject="x" * (CONFIG.max_value_chars * 3)))

    async def go() -> None:
        subject = str(items_of(await w.check(mail_watch(1, baseline=None)))["m0001"]["subject"])
        assert subject == "x" * CONFIG.max_value_chars
    run(go())


def test_each_watch_reads_its_own_mailbox_in_one_tick() -> None:
    w = World(resources=FakeResources({ADDRESS: 11, OTHER_ADDRESS: 12}))
    w.inbox(msg(1), connection=11)
    w.inbox(msg(2), msg(3), connection=12)

    async def go() -> None:
        got = await w.tick(mail_watch(1, baseline=None), mail_watch(2, target=OTHER_ADDRESS, baseline=None))
        assert set(items_of(got[1])) == {"m0001"} and set(items_of(got[2])) == {"m0002", "m0003"}
        assert {c for c, _ in w.mailbox.queries} == {11, 12}
    run(go())


def test_a_mailbox_the_person_cannot_use_fails_not_connected_and_reaches_no_mail() -> None:
    w = World()
    w.inbox(msg(1))

    async def go() -> None:
        check = await w.check(mail_watch(1, target=OTHER_ADDRESS, baseline=None))
        assert check == Failed("not_connected") and w.mailbox.queries == []
    run(go())


def test_an_unreachable_mailbox_fails_unreachable_and_is_never_an_empty_inbox() -> None:
    w = World()
    w.inbox(msg(1))
    w.mailbox.fail[11] = MailFailed("unreachable")

    async def go() -> None:
        assert await w.check(mail_watch(1, baseline=None)) == Failed("unreachable")
        assert isinstance(await w.check(mail_watch(1, baseline={})), Failed)
    run(go())


def test_a_refused_or_reconnecting_mailbox_is_a_failure_never_every_message_gone() -> None:
    w = World()
    w.inbox(msg(1))
    base = {"m0001": {"from": SENDER, "subject": "s", "unread": True, "labels": ""}}

    async def go() -> None:
        reasons: tuple[Reason, ...] = ("refused", "needs_reconnect", "not_found")
        for reason in reasons:
            w.mailbox.fail[11] = MailFailed(reason)
            assert isinstance(await w.check(mail_watch(1, baseline=base)), Failed), reason
    run(go())

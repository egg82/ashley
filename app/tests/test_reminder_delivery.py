"""A fired reminder is never lost silently, over a real database: its push is sent by the push singleton from her
stored answer (never through the outbox, which drops what waits past `stale_s`), and recorded on the reminder:
delivered takes it off the person's list; no browser, or a push that fails, leaves it listed `undelivered` at once and
tried again every `retry_s` for `deliver_for_s`. A firing the model refuses is tried again later a few times, then
listed `failed`. A listed reminder is never pruned until its person dismisses it. Her answer is also in the person's
conversation history. No log line carries what the reminder says."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from ashley import logs, services
from ashley.channels.push import reminders as push_reminders
from ashley.channels.push.config import load as push_config
from ashley.channels.push.sender import Sent
from ashley.channels.push.subscriptions import Subscription
from ashley.channels.wake import runner
from ashley.conversations.conversations import Conversations
from ashley.inference.inference import InferenceRefused
from ashley.people.model import Household, Person
from ashley.people.people import People
from ashley.senses.repeat import Repeat
from contract.conversations_support import db_url as db_url, events, migrated_template as migrated_template
from contract.conversations_support import run, scalar
from push_support import FakeSender, FakeSubscriptions, browser, subscriptions as subscriptions
from test_reminder_turn import BRIEF, SAYS, Home, world

CONFIG = push_config()


def state(url: str, wake_id: int) -> tuple[str | None, int]:
    got = scalar(url, "SELECT json_build_array(delivery, delivery_attempts) FROM wakes WHERE id = %s", (wake_id,))
    return got[0], int(got[1])


def age(url: str, wake_id: int, column: str, seconds: int) -> None:
    scalar(url, f"WITH u AS (UPDATE wakes SET {column} = {column} - make_interval(secs => %s) WHERE id = %s "
                "RETURNING 1) SELECT count(*) FROM u", (seconds, wake_id))


def test_a_fired_reminder_is_pushed_from_her_answer_once_and_leaves_the_list(
        db_url: str, subscriptions: FakeSubscriptions) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            subscriptions.rows.append(Subscription(1, w.home, w.alana, browser()))
            sender = FakeSender()
            fired = await w.remind()
            w.model.script = [SAYS]
            await runner.sweep()
            assert w.queued() == [] and state(db_url, fired) == ("sending", 0)
            [listed] = await w.wakes.reminders(w.home, w.alana)
            assert listed.state == "sending"
            assert await push_reminders.deliver(sender, CONFIG) == 1
            assert [n.body for _, n in sender.sends] == [SAYS.text]
            assert state(db_url, fired) == ("delivered", 1)
            assert await w.wakes.reminders(w.home, w.alana) == ()
            assert await push_reminders.deliver(sender, CONFIG) == 0 and len(sender.sends) == 1
    run(go())


def test_with_no_browser_it_is_undelivered_at_once_and_delivered_when_one_appears(
        db_url: str, subscriptions: FakeSubscriptions) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            sender = FakeSender()
            fired = await w.remind()
            w.model.script = [SAYS]
            await runner.sweep()
            assert await push_reminders.deliver(sender, CONFIG) == 1
            assert state(db_url, fired) == ("undelivered", 1)
            [listed] = await w.wakes.reminders(w.home, w.alana)
            assert (listed.id, listed.state) == (fired, "undelivered")
            assert await push_reminders.deliver(sender, CONFIG) == 0
            subscriptions.rows.append(Subscription(1, w.home, w.alana, browser()))
            age(db_url, fired, "delivery_tried_at", int(runner.CONFIG.retry_s) + 1)
            assert await push_reminders.deliver(sender, CONFIG) == 1
            assert state(db_url, fired) == ("delivered", 2) and len(sender.sends) == 1
    run(go())


def test_a_push_that_keeps_failing_is_tried_for_a_day_and_stays_listed_undelivered(
        db_url: str, subscriptions: FakeSubscriptions) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            subscriptions.rows.append(Subscription(1, w.home, w.alana, browser()))
            sender = FakeSender({browser().endpoint: Sent("failed", 500)})
            fired = await w.remind()
            w.model.script = [SAYS]
            await runner.sweep()
            assert await push_reminders.deliver(sender, CONFIG) == 1
            age(db_url, fired, "delivery_tried_at", int(runner.CONFIG.retry_s) + 1)
            assert await push_reminders.deliver(sender, CONFIG) == 1
            assert state(db_url, fired) == ("undelivered", 2)
            age(db_url, fired, "settled_at", int(runner.CONFIG.deliver_for_s) + 1)
            age(db_url, fired, "delivery_tried_at", int(runner.CONFIG.retry_s) + 1)
            assert await push_reminders.deliver(sender, CONFIG) == 0
            [listed] = await w.wakes.reminders(w.home, w.alana)
            assert listed.state == "undelivered"
    run(go())


def test_a_listed_reminder_is_never_pruned_until_dismissed(db_url: str, subscriptions: FakeSubscriptions) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            fired = await w.remind()
            w.model.script = [SAYS]
            await runner.sweep()
            await push_reminders.deliver(FakeSender(), CONFIG)
            age(db_url, fired, "settled_at", 30 * 86400)
            assert await w.wakes.prune(runner.CONFIG.keep_s) == 0
            assert not await w.wakes.dismiss(w.home, w.sam, fired)
            assert await w.wakes.dismiss(w.home, w.alana, fired)
            assert await w.wakes.reminders(w.home, w.alana) == ()
            assert await w.wakes.prune(runner.CONFIG.keep_s) == 1
    run(go())


def test_her_answer_is_in_the_persons_conversation_history(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.remind()
            w.model.script = [SAYS]
            await runner.sweep()
            page = await services.get(Conversations).of_person(w.home, w.alana, 10)
            [summary] = page.items
            conversation = await services.get(Conversations).get(summary.id)
            assert conversation is not None and conversation.turns[-1].text == SAYS.text
    run(go())


def test_a_refused_one_off_is_tried_again_later_then_listed_failed(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            fired = await w.remind()
            w.model.script = [InferenceRefused("no")] * runner.CONFIG.fire_attempts
            for attempt in range(1, runner.CONFIG.fire_attempts + 1):
                assert await runner.sweep() == 1
                if attempt < runner.CONFIG.fire_attempts:
                    assert w.outcome(fired) is None and await runner.sweep() == 0
                    age(db_url, fired, "due_at", int(runner.CONFIG.retry_s) + 1)
            assert w.outcome(fired) == "failed" and len(w.model.prompts) == runner.CONFIG.fire_attempts
            [listed] = await w.wakes.reminders(w.home, w.alana)
            assert (listed.id, listed.state) == (fired, "failed")
            assert await w.wakes.prune(0) == 0
    run(go())


def test_an_occurrence_for_someone_no_longer_of_the_household_settles_and_the_series_goes_on(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            fired = await w.remind(for_id=w.sam, by=w.alana, repeat=Repeat("daily", 1, datetime(2026, 10, 1, 9, 0)))
            services.unregister(People)
            services.register(People, Home(Household(w.home, "home", "America/Denver", "", (Person(w.alana, w.home, "Alana"),))))
            for attempt in range(1, runner.CONFIG.fire_attempts + 1):
                assert await runner.sweep() == 1
                if attempt < runner.CONFIG.fire_attempts:
                    age(db_url, fired, "due_at", int(runner.CONFIG.retry_s) + 1)
            assert w.outcome(fired) == "no_person" and w.model.prompts == []
            [(_, due_at)] = w.waiting()
            assert datetime.now(UTC) < due_at < datetime.now(UTC) + timedelta(days=2)
    run(go())


def test_a_refused_occurrence_that_then_answers_fires_once(db_url: str, subscriptions: FakeSubscriptions) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            fired = await w.remind(repeat=Repeat("daily", 1, datetime(2026, 10, 1, 9, 0)))
            w.model.script = [InferenceRefused("no"), SAYS]
            await runner.sweep()
            age(db_url, fired, "due_at", int(runner.CONFIG.retry_s) + 1)
            await runner.sweep()
            assert w.outcome(fired) == "turn" and len(w.waiting()) == 1
    run(go())


def test_no_delivery_log_line_carries_what_the_reminder_says(db_url: str, subscriptions: FakeSubscriptions,
                                                             capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with world(db_url) as w:
            subscriptions.rows.append(Subscription(1, w.home, w.alana, browser()))
            await w.remind()
            w.model.script = [SAYS]
            await runner.sweep()
            await push_reminders.deliver(FakeSender(), CONFIG)
    run(go())
    out = capsys.readouterr().out
    [line] = events(out, "push.reminder")
    assert line["outcome"] == "delivered"
    for value in ("NGFCU", "Visa", BRIEF[:20]):
        assert value not in out, value


def test_dismiss_never_hides_a_reminder_still_to_fire(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            waiting = await w.remind(due_at=datetime.now(UTC) + timedelta(hours=1))
            assert not await w.wakes.dismiss(w.home, w.alana, waiting)
            [listed] = await w.wakes.reminders(w.home, w.alana)
            assert (listed.id, listed.state) == (waiting, "scheduled")
    run(go())


def test_a_reminder_dismissed_before_its_retry_is_not_pushed_again(
        db_url: str, subscriptions: FakeSubscriptions) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            subscriptions.rows.append(Subscription(1, w.home, w.alana, browser()))
            sender = FakeSender({browser().endpoint: Sent("failed", 500)})
            fired = await w.remind()
            w.model.script = [SAYS]
            await runner.sweep()
            assert await push_reminders.deliver(sender, CONFIG) == 1
            assert await w.wakes.dismiss(w.home, w.alana, fired)
            age(db_url, fired, "delivery_tried_at", int(runner.CONFIG.retry_s) + 1)
            assert await w.wakes.undelivered(10, runner.CONFIG.retry_s, 86400.0) == ()
            assert await push_reminders.deliver(sender, CONFIG) == 0 and len(sender.sends) == 1
    run(go())


def test_two_passes_at_once_deliver_a_reminder_once(db_url: str, subscriptions: FakeSubscriptions) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            subscriptions.rows.append(Subscription(1, w.home, w.alana, browser()))
            first, second = FakeSender(), FakeSender()
            fired = await w.remind()
            w.model.script = [SAYS]
            await runner.sweep()
            tried = await asyncio.gather(push_reminders.deliver(first, CONFIG), push_reminders.deliver(second, CONFIG))
            assert sorted(tried) == [0, 1] and len(first.sends) + len(second.sends) == 1
            assert state(db_url, fired) == ("delivered", 1)
    run(go())


def test_a_dismissed_reminder_is_not_handed_out_for_another_push_and_a_try_is_claimed_once(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            fired = await w.remind()
            w.model.script = [SAYS]
            await runner.sweep()
            assert [d.id for d in await w.wakes.undelivered(10, 300.0, 86400.0)] == [fired]
            assert await w.wakes.claim(fired, 300.0) is True and await w.wakes.claim(fired, 300.0) is False
            assert await w.wakes.dismiss(w.home, w.alana, fired)
            age(db_url, fired, "delivery_tried_at", 301)
            assert await w.wakes.undelivered(10, 300.0, 86400.0) == () and await w.wakes.claim(fired, 300.0) is False
    run(go())

"""A fired reminder is delivered by the push singleton (`push.reminders.deliver`) from her stored answer, every try
recorded on the wake: undelivered at once when nothing reached a phone, retried every `retry_s` for `deliver_for_s`,
then given up but still listed; her words are also in the person's web history; a firing that could not run is
refired up to `fire_attempts` times, then settled; never twice, whichever pod runs the singleton."""

import asyncio
from dataclasses import replace
from functools import partial
from typing import Any

import psycopg
import pytest
from ashley.channels.push import later, reminders as push_reminders
from ashley.channels.push.config import load as load_push_config
from ashley.channels.push.sender import Sent
from ashley.channels.wake import runner
from ashley.channels.wake.config import CONFIG as WAKES
from ashley.conversations.conversations import Conversations
from ashley import services
from ashley.referee.etcd_lease import EtcdLease
from contract.conversations_support import run, scalar
from contract.test_inflight_resume import World
from etcd import etcd_url
from contract.lease_support import campaign, here, unique_name, wait_until
from rb_support import DONE, FakeSender, stack
from rb_delivery_support import GONE, REFUSED, HangingSender, delivery, fired, listed, states, window

@pytest.fixture(autouse=True)
def quick_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """The retry delay scaled from 300 s to a fifth of a second; the window stays a day."""
    monkeypatch.setattr(push_reminders, "WAKES", replace(WAKES, retry_s=0.2))



def test_the_shipped_tunables_are_a_300_second_retry_for_a_day_and_three_firings() -> None:
    assert (WAKES.retry_s, WAKES.deliver_for_s, WAKES.fire_attempts) == (300.0, 86400.0, 3)


def test_a_fired_reminder_is_sending_until_the_singleton_delivers_it_to_the_person_alone(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            await fired(s, world)
            assert await states(s) == ["sending"] and s.sender.sent == []
            assert await s.deliver() == 1
            assert [e.split("/")[3] for e, _ in s.sender.sent] == [str(s.alana)]
            assert await listed(s) == () and s.outbox() == 0

    run(go())


def test_the_notification_carries_her_stored_answer(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            id_ = await fired(s, world)
            answer = await services.get(Conversations).answer_to(s.house, f"wake:{id_}")
            assert answer is not None and answer.text == DONE.text and answer.author == "ashley"
            await s.deliver()
            ((_, body),) = s.sender.sent
            assert DONE.text in body

    run(go())


def test_it_goes_to_every_browser_of_the_person_and_to_none_of_anyone_elses(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            s.subs.give(s.house, s.alana)
            s.subs.give(s.house, s.alana)
            await fired(s, world)
            await s.deliver()
            assert [e.split("/")[3] for e, _ in s.sender.sent] == [str(s.alana)] * 3
            assert len({e for e, _ in s.sender.sent}) == 3

    run(go())


def test_one_for_sam_set_by_alana_goes_to_sams_browsers_and_is_sams_to_dismiss(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            await fired(s, world, who=s.sam.id, by=s.alana)
            await s.deliver()
            assert [e.split("/")[3] for e, _ in s.sender.sent] == [str(s.sam.id)]

    run(go())


def test_a_delivered_reminder_is_not_sent_again(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            await fired(s, world)
            assert await s.deliver() == 1
            await asyncio.sleep(0.4)
            assert await s.deliver() == 0 and len(s.sender.sent) == 1

    run(go())


def test_with_no_subscription_it_is_undelivered_at_once_and_still_listed(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            s.subs.rows.clear()
            await fired(s, world)
            assert await s.deliver() == 1
            assert await states(s) == ["undelivered"] and s.sender.sent == []
            assert await s.deliver() == 0

    run(go())


def test_a_failed_send_is_undelivered_at_once_and_retried_after_the_delay_until_it_gets_through(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            s.sender.outcome = REFUSED
            id_ = await fired(s, world)
            assert await s.deliver() == 1 and await states(s) == ["undelivered"]
            assert await s.deliver() == 0 and len(s.sender.sent) == 1
            await asyncio.sleep(0.3)
            assert await s.deliver() == 1 and len(s.sender.sent) == 2 and await states(s) == ["undelivered"]
            assert [d.attempts for d in await s.wakes.undelivered(10, 0.0, 86400.0) if d.id == id_] == [2]
            s.sender.outcome = Sent("ok", 201)
            await asyncio.sleep(0.3)
            assert await s.deliver() == 1 and len(s.sender.sent) == 3
            assert await listed(s) == () and await s.deliver() == 0

    run(go())


def test_a_push_service_that_says_gone_leaves_it_undelivered_and_forgets_that_browser(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            s.sender.outcome = GONE
            await fired(s, world)
            await s.deliver()
            assert await states(s) == ["undelivered"]
            assert [r.person_id for r in s.subs.rows] == [s.sam.id]

    run(go())


def test_one_browser_reached_among_failures_is_delivered(world: World) -> None:
    class Mixed(FakeSender):
        async def send(self, browser: Any, notification: Any) -> Sent:
            await super().send(browser, notification)
            return Sent("ok", 201) if len(self.sent) == 2 else REFUSED

    async def go() -> None:
        async with stack(world) as s:
            s.sender = Mixed()
            s.subs.give(s.house, s.alana)
            await fired(s, world)
            await s.deliver()
            assert len(s.sender.sent) == 2 and await listed(s) == ()

    run(go())


def test_a_subscription_made_after_the_first_failure_is_reached_on_the_retry(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            s.subs.rows.clear()
            await fired(s, world)
            await s.deliver()
            assert await states(s) == ["undelivered"]
            s.subs.give(s.house, s.alana)
            await asyncio.sleep(0.3)
            await s.deliver()
            assert len(s.sender.sent) == 1 and await listed(s) == ()

    run(go())


def test_it_is_given_up_after_the_window_but_stays_listed_and_unpruned_until_dismissed(
        world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    window(monkeypatch, 0.6)

    async def go() -> None:
        async with stack(world) as s:
            s.sender.outcome = REFUSED
            id_ = await fired(s, world)
            tries = 0
            for _ in range(10):
                tries += await s.deliver()
                await asyncio.sleep(0.12)
            assert 2 <= tries <= 7 and len(s.sender.sent) == tries
            await asyncio.sleep(0.5)
            assert await s.deliver() == 0 and len(s.sender.sent) == tries
            assert await states(s) == ["undelivered"]
            with psycopg.connect(world.url, autocommit=True) as conn:
                conn.execute("UPDATE wakes SET settled_at = settled_at - interval '30 days'")
            await runner.sweep()
            assert await states(s) == ["undelivered"]
            assert await s.wakes.dismiss(s.house, s.alana, id_) is True
            await runner.sweep()
            assert scalar(world.url, "SELECT count(*) FROM wakes WHERE id = %s", (id_,)) == 0

    run(go())


def test_a_fired_reminder_whose_answer_is_not_stored_is_not_tried_and_stays_sending(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            id_ = await s.schedule()
            assert await s.wakes.settle(id_, "turn") is True
            assert await s.deliver() == 0
            assert s.sender.sent == [] and await states(s) == ["sending"]

    run(go())


def test_her_words_are_in_the_persons_web_history_on_their_push_thread(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            await fired(s, world)
            convs = services.get(Conversations)
            mine = await convs.on_thread(s.house, f"push:{s.alana}")
            assert mine is not None and [t.text for t in mine.turns if t.author == "ashley"] == [DONE.text]
            assert await convs.on_thread(s.house, f"push:{s.sam.id}") is None
            page = await convs.of_person(s.house, s.alana, 10)
            assert [i.id for i in page.items] == [mine.id]

    run(go())


def test_one_for_sam_set_by_alana_is_in_sams_history_not_alanas(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            await fired(s, world, who=s.sam.id, by=s.alana)
            convs = services.get(Conversations)
            theirs = await convs.on_thread(s.house, f"push:{s.sam.id}")
            assert theirs is not None and [t.text for t in theirs.turns if t.author == "ashley"] == [DONE.text]
            assert await convs.on_thread(s.house, f"push:{s.alana}") is None

    run(go())


def test_it_is_in_the_history_even_when_no_push_ever_reaches_a_phone(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            s.subs.rows.clear()
            await fired(s, world)
            await s.deliver()
            mine = await services.get(Conversations).on_thread(s.house, f"push:{s.alana}")
            assert mine is not None and DONE.text in [t.text for t in mine.turns]

    run(go())


def test_two_pods_under_the_push_lease_deliver_a_reminder_once(world: World) -> None:
    url, name = etcd_url(), unique_name()

    async def go() -> None:
        async with stack(world) as s:
            id_ = await fired(s, world)
            sender_b = FakeSender()
            config = load_push_config()
            body_a = partial(later.drain, s.sender, config, 0.05, asyncio.sleep)
            body_b = partial(later.drain, sender_b, config, 0.05, asyncio.sleep)
            async with campaign(EtcdLease(url, here(), ttl=3, holder="a"), name, body_a):
                async with campaign(EtcdLease(url, here(), ttl=3, holder="b"), name, body_b):
                    await wait_until(lambda: delivery(world, id_) == "delivered")
                    await asyncio.sleep(0.6)
            assert len(s.sender.sent) + len(sender_b.sent) == 1
            assert await listed(s) == ()

    run(go())


def test_when_the_holder_stops_the_other_pod_takes_over_the_retries_and_it_arrives_once(world: World) -> None:
    url, name = etcd_url(), unique_name()

    async def go() -> None:
        async with stack(world) as s:
            s.sender.outcome = REFUSED
            id_ = await fired(s, world)
            sender_b = FakeSender()
            config = load_push_config()
            async with campaign(EtcdLease(url, here(), ttl=3, holder="a"), name,
                                partial(later.drain, s.sender, config, 0.05, asyncio.sleep)):
                await wait_until(lambda: delivery(world, id_) == "undelivered")
            assert len(s.sender.sent) == 1 and await states(s) == ["undelivered"]
            async with campaign(EtcdLease(url, here(), ttl=3, holder="b"), name,
                                partial(later.drain, sender_b, config, 0.05, asyncio.sleep)):
                await wait_until(lambda: delivery(world, id_) == "delivered")
                await asyncio.sleep(0.6)
            assert len(sender_b.sent) == 1 and await listed(s) == ()

    run(go())


def test_a_holder_stopped_mid_try_leaves_it_sending_and_the_next_holder_delivers_it_once(world: World) -> None:
    url, name = etcd_url(), unique_name()

    async def go() -> None:
        async with stack(world) as s:
            id_ = await fired(s, world)
            stuck, sender_b = HangingSender(), FakeSender()
            config = load_push_config()
            async with campaign(EtcdLease(url, here(), ttl=3, holder="a"), name,
                                partial(later.drain, stuck, config, 0.05, asyncio.sleep)):
                await wait_until(lambda: len(stuck.sent) >= 1)
            assert delivery(world, id_) == "sending"
            async with campaign(EtcdLease(url, here(), ttl=3, holder="b"), name,
                                partial(later.drain, sender_b, config, 0.05, asyncio.sleep)):
                await wait_until(lambda: delivery(world, id_) == "delivered", timeout=1.5)
                await asyncio.sleep(0.6)
            assert len(stuck.sent) == 1 and len(sender_b.sent) == 1 and await listed(s) == ()

    run(go())


def test_two_passes_at_once_deliver_a_reminder_once(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            sender_b = FakeSender()
            await fired(s, world)
            config = load_push_config()
            await asyncio.gather(push_reminders.deliver(s.sender, config), push_reminders.deliver(sender_b, config))
            assert len(s.sender.sent) + len(sender_b.sent) == 1

    run(go())


def test_a_reminder_dismissed_before_its_retry_is_not_pushed_again(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            s.sender.outcome = REFUSED
            id_ = await fired(s, world)
            await s.deliver()
            assert await s.wakes.dismiss(s.house, s.alana, id_) is True
            s.sender.outcome = Sent("ok", 201)
            await asyncio.sleep(0.3)
            await s.deliver()
            assert len(s.sender.sent) == 1

    run(go())

"""Shared by the delivery and refire blind suites: canned send results, the delivery window, firing a reminder,
and what the person's list shows."""

import asyncio
from dataclasses import replace
from typing import Any

import pytest
from ashley.channels.push import reminders as push_reminders
from ashley.channels.push.sender import Notification, Sent
from ashley.channels.push.subscriptions import Browser
from ashley.channels.wake import runner
from ashley.channels.wake.config import CONFIG as WAKES
from contract.conversations_support import scalar
from contract.test_inflight_resume import World
from rb_support import DONE, FakeSender, Stack

REFUSED = Sent("failed", 500)
GONE = Sent("gone", 410)


def window(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    monkeypatch.setattr(push_reminders, "WAKES", replace(WAKES, retry_s=0.1, deliver_for_s=seconds))


async def fired(s: Stack, world: World, **kw: Any) -> int:
    world.first.inference.script = [DONE]
    id_ = await s.schedule(**kw)
    assert await runner.sweep() >= 1
    return id_


def listed(s: Stack, who: int | None = None) -> Any:
    return s.wakes.reminders(s.house, s.alana if who is None else who)


async def states(s: Stack, who: int | None = None) -> list[str]:
    return [x.state for x in await listed(s, who)]


class HangingSender(FakeSender):
    """Records each send and never returns from it, as a holder stopped between taking a try and recording it."""

    async def send(self, browser: Browser, notification: Notification) -> Sent:
        self.sent.append((browser.endpoint, notification.body))
        await asyncio.Event().wait()
        return self.outcome


def delivery(world: World, wake_id: int) -> str:
    """The wake's push state as stored, read without the event loop, so a test can wait on it with `wait_until`."""
    return str(scalar(world.url, "SELECT delivery FROM wakes WHERE id = %s", (wake_id,)))

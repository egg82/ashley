"""`WarmPod.run`: keep the pod until cancelled; a failed call is logged (`looks.warm_failed`) and tried again at the
next tick, every `warm_tick_s`, and soon (`RECHECK_S`) after a pod was deleted."""

import asyncio
from contextlib import suppress
from typing import Any

import pytest
from ashley.looks.config import LooksConfig
from ashley.looks.warm_pod import NAME, RECHECK_S
from ashley.runs.kube_api import KubeError
from warm_blind_support import CONFIG, PREFIX, FakeKube, fields_of, go, keeper, log_text, with_config


class Ticks:
    """A sleep that records what it was asked for and cancels the run after `limit` of them."""

    def __init__(self, limit: int) -> None:
        self.asked: list[float] = []
        self.limit = limit

    async def __call__(self, seconds: float) -> None:
        self.asked.append(seconds)
        if len(self.asked) >= self.limit:
            raise asyncio.CancelledError
        await asyncio.sleep(0)


def run_until_cancelled(kube: FakeKube, sleep: Ticks, config: LooksConfig = CONFIG) -> None:
    pod = keeper(kube, config, sleep=sleep)

    async def scenario() -> None:
        with suppress(asyncio.CancelledError):
            await pod.run()

    go(scenario())


def test_it_makes_the_pod_and_waits_a_tick_between_looks() -> None:
    kube, sleep = FakeKube(), Ticks(3)
    run_until_cancelled(kube, sleep)
    assert kube.count("create") == 1
    assert sleep.asked == [CONFIG.warm_tick_s] * 3


def test_the_wait_is_the_configured_tick() -> None:
    sleep = Ticks(2)
    run_until_cancelled(FakeKube(), sleep, with_config(warm_tick_s=4.5))
    assert sleep.asked == [4.5, 4.5]


def test_after_deleting_a_pod_it_looks_again_soon() -> None:
    kube = FakeKube()
    first = keeper(kube)
    go(first.tick())
    kube.pods_by_name[NAME]["status"]["phase"] = "Failed"
    sleep = Ticks(2)
    run_until_cancelled(kube, sleep)
    assert sleep.asked[0] == RECHECK_S
    assert sleep.asked[1] == CONFIG.warm_tick_s
    assert kube.count("create") == 2


@pytest.mark.parametrize("verb", ["get", "create", "delete"])
def test_a_failed_call_is_logged_and_tried_again_at_the_next_tick(verb: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    kube = FakeKube()
    kube.fail[verb] = [KubeError("503"), KubeError("503")]
    if verb == "delete":
        go(keeper(kube).tick())
        kube.pods_by_name[NAME]["status"]["phase"] = "Failed"
    sleep = Ticks(6)
    run_until_cancelled(kube, sleep)
    assert fields_of(caplog, "looks.warm_failed")
    assert NAME in kube.pods_by_name and kube.pods_by_name[NAME]["status"]["phase"] != "Failed"
    assert len(sleep.asked) == 6


def test_a_failure_log_says_how_it_failed_and_never_the_page_prefix(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG")
    kube = FakeKube()
    kube.fail["get"] = [KubeError("500")]
    run_until_cancelled(kube, Ticks(2))
    assert PREFIX not in log_text(caplog) and "/look/" not in log_text(caplog)


def test_cancelling_the_run_ends_it() -> None:
    kube = FakeKube()
    pod = keeper(kube)

    async def scenario() -> None:
        task = asyncio.create_task(pod.run())
        while not kube.calls:
            await asyncio.sleep(0.01)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        assert task.done()

    go(scenario())


def test_a_cancel_during_a_kubernetes_call_is_not_swallowed() -> None:
    class Hang(FakeKube):
        def __init__(self) -> None:
            super().__init__()
            self.hung = asyncio.Event()

        async def pod(self, namespace: str, name: str) -> dict[str, Any] | None:
            self.hung.set()
            await asyncio.Event().wait()
            return None

    hang = Hang()
    pod = keeper(hang)

    async def scenario() -> None:
        task = asyncio.create_task(pod.run())
        await hang.hung.wait()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        assert task.done()

    go(scenario())

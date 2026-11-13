"""The warm looker against the real HTTP side of the warm pod (`shooter.handler`) with a pretend Playwright behind it:
a look is taken by the pod when it can and by a pod of its own when it cannot, never lost, never two at once in the
pod, and nothing one look left is there for the next."""

import asyncio
import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import httpx2
import pytest
from ashley.looks import shooter
from ashley.looks.looker import LookUnavailable, Shot
from ashley.looks.warm_looker import WarmLooker
from warm_blind_browser_support import PwError, Script, playwright
from warm_blind_support import CONFIG, LIMITS, PAGE_URL, TARGET, FakeCold, FakeKube, Pod, go, keeper, pod_server


@contextmanager
def warm_pod(script: Script, tmp: Path) -> Generator[Pod]:
    """The real handler with the real `serve_one` thread behind it, over the pretend Playwright."""
    api, p = playwright(script, tmp)
    stop = threading.Event()
    with pod_server(worker=False) as pod:
        def work() -> None:
            while not stop.is_set():
                if pod.jobs.qsize():
                    shooter.serve_one(pod.jobs, api, p, LIMITS, str(tmp))
                else:
                    stop.wait(0.01)

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        try:
            yield pod
        finally:
            stop.set()
            thread.join(2)


def warm_looker(pod: Pod, cold: FakeCold) -> WarmLooker:
    return WarmLooker(cold, keeper(FakeKube()), httpx2.AsyncClient(), pod.base, CONFIG)


def test_a_look_is_taken_by_the_warm_pod(tmp_path: Path) -> None:
    script, cold = Script(), FakeCold()
    with warm_pod(script, tmp_path) as pod:
        shot = go(warm_looker(pod, cold).look("look-a", TARGET))
    assert isinstance(shot, Shot) and shot.data.startswith(bytes.fromhex("ffd8ff"))
    assert cold.asked == [] and script.gotos == [PAGE_URL]


def test_a_page_that_never_draws_is_the_answer_and_costs_no_second_pod(tmp_path: Path) -> None:
    script, cold = Script(ready=False), FakeCold()
    with warm_pod(script, tmp_path) as pod, pytest.raises(LookUnavailable):
        go(warm_looker(pod, cold).look("look-a", TARGET))
    assert cold.asked == [] and script.launches == 1


def test_a_picture_too_large_is_the_answer_and_costs_no_second_pod(tmp_path: Path) -> None:
    script, cold = Script(scale=100_000), FakeCold()
    with warm_pod(script, tmp_path) as pod, pytest.raises(LookUnavailable):
        go(warm_looker(pod, cold).look("look-a", TARGET))
    assert cold.asked == []


def test_a_browser_that_cannot_start_in_the_pod_sends_the_look_to_a_pod_of_its_own(tmp_path: Path) -> None:
    script, cold = Script(launch_error=PwError("no")), FakeCold(b"cold")
    with warm_pod(script, tmp_path) as pod:
        assert go(warm_looker(pod, cold).look("look-a", TARGET)) == Shot(b"cold")
    assert len(cold.asked) == 1


def test_a_second_look_while_the_pod_is_busy_is_taken_in_a_pod_of_its_own(tmp_path: Path) -> None:
    hold = threading.Event()
    script, cold = Script(hold=hold), FakeCold(b"cold")
    with warm_pod(script, tmp_path) as pod:
        looker = warm_looker(pod, cold)

        async def scenario() -> list[Shot]:
            first = asyncio.create_task(looker.look("look-1", TARGET))
            while script.launches == 0:
                await asyncio.sleep(0.01)
            second = await looker.look("look-2", TARGET)
            hold.set()
            return [await first, second]

        shots = go(scenario())
    assert shots[1] == Shot(b"cold") and shots[0] != Shot(b"cold")
    assert cold.asked == [("look-2", TARGET)]
    assert script.launches == 1


def test_looks_in_the_pod_never_overlap_and_each_has_its_own_browser(tmp_path: Path) -> None:
    script, cold = Script(delay_s=0.1), FakeCold(b"cold")
    with warm_pod(script, tmp_path) as pod:
        looker = warm_looker(pod, cold)

        async def scenario() -> list[Shot]:
            return list(await asyncio.gather(*(looker.look(f"look-{i}", TARGET) for i in range(6))))

        shots = go(scenario())
    assert len(shots) == 6
    kinds = [kind for kind, _ in script.events]
    assert kinds == ["launch", "close"] * (len(kinds) // 2)
    assert len(cold.asked) + script.launches == 6


def test_nothing_one_look_left_is_there_for_the_next(tmp_path: Path) -> None:
    script = Script(leave=("profile/", "cookie.txt"))
    with warm_pod(script, tmp_path) as pod:
        looker = warm_looker(pod, FakeCold())
        for i in range(3):
            go(looker.look(f"look-{i}", TARGET))
    assert script.launches == 3
    assert script.seen_tmp == [[], [], []]
    assert list(tmp_path.iterdir()) == []


def test_a_page_address_outside_the_look_page_is_never_opened_and_the_look_is_not_lost(tmp_path: Path) -> None:
    class Wrong(FakeCold):
        def url(self, target: object) -> str:
            return "http://evil.example/look/steal"

    script, cold = Script(), Wrong(b"cold")
    with warm_pod(script, tmp_path) as pod:
        assert go(warm_looker(pod, cold).look("look-a", TARGET)) == Shot(b"cold")
    assert script.gotos == [] and script.launches == 0


def test_a_pod_nobody_listens_on_is_a_pod_of_its_own() -> None:
    cold = FakeCold(b"cold")
    looker = WarmLooker(cold, keeper(FakeKube()), httpx2.AsyncClient(), "http://127.0.0.1:1", CONFIG)
    assert go(looker.look("look-a", TARGET)) == Shot(b"cold")

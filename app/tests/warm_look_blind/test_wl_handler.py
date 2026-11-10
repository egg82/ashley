"""`shooter.handler`: the warm pod's HTTP side. `POST /look` with `{"url": ...}` is answered with the look's line;
the gate admits one look at a time and a second gets 503; `GET /healthz` says it is ready; nothing else is served and a
bad request never reaches the browser."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from ashley.looks import shooter
from warm_blind_support import JPEG, PAGE_URL, PREFIX, line_of, pod_server


def test_a_look_is_answered_with_the_workers_line() -> None:
    with pod_server() as pod:
        r = pod.look(PAGE_URL)
    assert r.status_code == 200
    assert r.text.strip() == line_of(JPEG)
    assert pod.seen == [PAGE_URL]


def test_a_failed_look_is_answered_with_its_failed_line_and_ok() -> None:
    with pod_server(answer=lambda url: shooter.FAILED + "not_ready") as pod:
        r = pod.look(PAGE_URL)
    assert r.status_code == 200 and r.text.strip() == shooter.FAILED + "not_ready"


def test_healthz_is_ok() -> None:
    with pod_server(worker=False) as pod:
        import httpx2
        assert httpx2.get(pod.base + "/healthz").status_code == 200


def test_healthz_answers_while_a_look_is_running() -> None:
    import httpx2
    release = threading.Event()

    def slow(url: str) -> str:
        release.wait(5)
        return line_of(JPEG)

    with pod_server(answer=slow) as pod, ThreadPoolExecutor(1) as ex:
        running = ex.submit(pod.look, PAGE_URL)
        deadline = time.monotonic() + 5
        while not pod.seen and time.monotonic() < deadline:
            time.sleep(0.01)
        assert httpx2.get(pod.base + "/healthz").status_code == 200
        release.set()
        assert running.result().status_code == 200


def test_a_second_look_while_one_runs_gets_503_and_never_reaches_the_worker() -> None:
    release = threading.Event()

    def slow(url: str) -> str:
        release.wait(5)
        return line_of(JPEG)

    with pod_server(answer=slow) as pod, ThreadPoolExecutor(1) as ex:
        first = ex.submit(pod.look, PAGE_URL)
        deadline = time.monotonic() + 5
        while not pod.seen and time.monotonic() < deadline:
            time.sleep(0.01)
        second = pod.look(PREFIX + "other")
        assert second.status_code == 503
        release.set()
        assert first.result().status_code == 200
    assert pod.seen == [PAGE_URL]


def test_a_look_after_a_finished_one_is_taken() -> None:
    with pod_server() as pod:
        assert [pod.look(PREFIX + str(i)).status_code for i in range(3)] == [200, 200, 200]
    assert pod.seen == [PREFIX + "0", PREFIX + "1", PREFIX + "2"]


def test_a_held_gate_is_busy() -> None:
    with pod_server() as pod:
        assert pod.gate.acquire(blocking=False)
        try:
            assert pod.look(PAGE_URL).status_code == 503
            assert pod.jobs.empty() and pod.seen == []
        finally:
            pod.gate.release()
        assert pod.look(PAGE_URL).status_code == 200


def test_the_gate_is_free_after_every_kind_of_request() -> None:
    with pod_server() as pod:
        pod.post("not json")
        pod.look("https://evil.example/look/x")
        pod.post(json.dumps({"nope": 1}))
        pod.post(b"x" * (shooter.MAX_BODY + 1))
        assert not pod.gate.locked()
        assert pod.look(PAGE_URL).status_code == 200


def test_a_worker_that_never_answers_frees_the_gate_and_is_not_a_picture() -> None:
    with pod_server(wait_s=0.2, answer=lambda url: time.sleep(0.6) or line_of(JPEG)) as pod:
        r = pod.look(PAGE_URL)
        assert r.status_code != 200 or shooter.MARK not in r.text
        assert not pod.gate.locked()


@pytest.mark.parametrize("body", ["not json", "[]", "null", '"text"', "{}", '{"url": 5}', '{"url": null}', '{"url": ["' + PREFIX + 'x"]}', ""])
def test_a_body_that_is_not_a_look_is_refused_before_the_browser(body: str) -> None:
    with pod_server() as pod:
        r = pod.post(body)
    assert 400 <= r.status_code < 500
    assert pod.seen == [] and pod.jobs.empty()


def test_a_body_over_the_limit_is_refused_before_the_browser() -> None:
    padded = json.dumps({"url": PREFIX + "a" * shooter.MAX_BODY})
    with pod_server() as pod:
        r = pod.post(padded)
    assert 400 <= r.status_code < 500
    assert pod.seen == []


@pytest.mark.parametrize("path", ["/", "/shoot", "/look/x", "/healthz", "/Look"])
def test_a_post_to_any_other_path_is_not_a_look(path: str) -> None:
    with pod_server() as pod:
        r = pod.post(json.dumps({"url": PAGE_URL}), path=path)
    assert r.status_code >= 400
    assert pod.seen == []


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE", "PATCH"])
def test_other_methods_on_look_are_not_a_look(method: str) -> None:
    import httpx2
    with pod_server() as pod:
        r = httpx2.request(method, pod.base + "/look", content=json.dumps({"url": PAGE_URL}))
    assert r.status_code >= 400
    assert pod.seen == []


def test_the_pod_goes_on_serving_after_bad_requests() -> None:
    with pod_server() as pod:
        for body in ("x", "{", b"\xff\xfe", "[1]"):
            pod.post(body)
        assert pod.look(PAGE_URL).status_code == 200


def test_a_look_never_writes_its_address_to_stderr(capfd: pytest.CaptureFixture[str]) -> None:
    with pod_server() as pod:
        pod.look(PAGE_URL)
        pod.look("https://evil.example/" + "SECRETzq")
    out = capfd.readouterr()
    assert "TOKENzq9x7" not in out.out + out.err and "SECRETzq" not in out.out + out.err

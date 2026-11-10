"""The warm pod's program (`shooter.serve_one`, `shooter.handler`): every look gets a browser of its own that is closed
after, what a look leaves in the temp directory is gone before the next, one look runs at a time, and only the app's
look page is opened."""

import http.client
import json
import queue
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from ashley.looks import shooter
from warm_look_support import LIMITS, body, line_is_picture, playwright

PREFIX = "http://app.test:8080/look/"


def one(jobs: "queue.Queue[shooter.Job]", url: str) -> "queue.Queue[str]":
    reply: "queue.Queue[str]" = queue.Queue()
    jobs.put((url, reply))
    return reply


def test_each_look_launches_and_closes_its_own_browser(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    api, p, launched = playwright(monkeypatch, str(tmp_path))
    jobs: "queue.Queue[shooter.Job]" = queue.Queue()
    first, second = one(jobs, PREFIX + "a"), one(jobs, PREFIX + "b")
    shooter.serve_one(jobs, api, p, LIMITS, str(tmp_path))
    shooter.serve_one(jobs, api, p, LIMITS, str(tmp_path))
    assert line_is_picture(first.get_nowait()) and line_is_picture(second.get_nowait())
    assert launched.opened == [PREFIX + "a", PREFIX + "b"]
    assert launched.closed == [1, 2]


def test_what_a_look_left_in_the_temp_directory_is_gone_and_what_was_there_stays(monkeypatch: pytest.MonkeyPatch,
                                                                                tmp_path: Path) -> None:
    (tmp_path / "driver").write_text("the driver's own")
    api, p, _ = playwright(monkeypatch, str(tmp_path))
    jobs: "queue.Queue[shooter.Job]" = queue.Queue()
    one(jobs, PREFIX + "a")
    shooter.serve_one(jobs, api, p, LIMITS, str(tmp_path))
    assert sorted(f.name for f in tmp_path.iterdir()) == ["driver"]


def test_a_look_that_fails_is_cleaned_up_and_the_next_look_is_taken(monkeypatch: pytest.MonkeyPatch,
                                                                    tmp_path: Path) -> None:
    api, p, launched = playwright(monkeypatch, str(tmp_path), fail_on=1)
    jobs: "queue.Queue[shooter.Job]" = queue.Queue()
    broken, fine = one(jobs, PREFIX + "a"), one(jobs, PREFIX + "b")
    shooter.serve_one(jobs, api, p, LIMITS, str(tmp_path))
    shooter.serve_one(jobs, api, p, LIMITS, str(tmp_path))
    assert broken.get_nowait() == shooter.FAILED + "browser"
    assert line_is_picture(fine.get_nowait())
    assert launched.closed == [1, 2] and list(tmp_path.iterdir()) == []


def test_clear_removes_directories_and_files_made_since_and_nothing_else(tmp_path: Path) -> None:
    (tmp_path / "kept").write_text("x")
    before = {"kept"}
    (tmp_path / "playwright-profile").mkdir()
    (tmp_path / "playwright-profile" / "Cookies").write_text("session")
    (tmp_path / "shot.tmp").write_text("x")
    shooter.clear(str(tmp_path), before)
    assert [f.name for f in tmp_path.iterdir()] == ["kept"]


class Warm:
    """The HTTP side on a free port, with a worker thread standing in for the Playwright thread."""

    def __init__(self, wait_s: float = 2.0) -> None:
        self.jobs: "queue.Queue[shooter.Job]" = queue.Queue()
        self.gate = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), shooter.handler(PREFIX, self.jobs, self.gate, wait_s))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def call(self, method: str, path: str, payload: bytes = b"") -> tuple[int, str]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=payload or None, headers={"Content-Length": str(len(payload))})
            got = conn.getresponse()
            return got.status, got.read().decode()
        finally:
            conn.close()

    def answer_next(self, line: str) -> threading.Thread:
        def work() -> None:
            _, reply = self.jobs.get(timeout=5)
            reply.put(line)

        thread = threading.Thread(target=work)
        thread.start()
        return thread


@pytest.fixture
def warm() -> Iterator[Warm]:
    w = Warm()
    yield w
    w.server.shutdown()
    w.server.server_close()


def test_a_look_under_the_prefix_is_answered_with_the_line(warm: Warm) -> None:
    worker = warm.answer_next("ashley-look AAAA")
    assert warm.call("POST", "/look", body(PREFIX + "token")) == (200, "ashley-look AAAA")
    worker.join()


def test_health_is_ready_and_anything_else_is_not_found(warm: Warm) -> None:
    assert warm.call("GET", "/healthz")[0] == 200
    assert warm.call("GET", "/look")[0] == 404 and warm.call("POST", "/elsewhere", b"{}")[0] == 404


@pytest.mark.parametrize("payload", [body("http://elsewhere.test/look/x"), body("http://app.test:8080/other"),
                                      b"not json", json.dumps({"url": 5}).encode(), b"{}", b"[]"])
def test_a_request_that_is_not_a_page_of_the_app_is_refused_and_opens_nothing(warm: Warm, payload: bytes) -> None:
    assert warm.call("POST", "/look", payload)[0] == 400
    assert warm.jobs.empty()


def test_a_look_while_another_runs_is_busy(warm: Warm) -> None:
    results: list[tuple[int, str]] = []
    first = threading.Thread(target=lambda: results.append(warm.call("POST", "/look", body(PREFIX + "a"))))
    first.start()
    _, reply = warm.jobs.get(timeout=5)
    assert warm.call("POST", "/look", body(PREFIX + "b"))[0] == 503
    reply.put("ashley-look BBBB")
    first.join()
    assert results == [(200, "ashley-look BBBB")]
    worker = warm.answer_next("ashley-look CCCC")
    assert warm.call("POST", "/look", body(PREFIX + "c"))[0] == 200
    worker.join()


def test_a_look_nothing_takes_times_out_and_frees_the_pod() -> None:
    w = Warm(wait_s=0.2)
    try:
        assert w.call("POST", "/look", body(PREFIX + "a"))[0] == 504
        assert not w.gate.locked()
    finally:
        w.server.shutdown()
        w.server.server_close()

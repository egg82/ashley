"""`WarmLooker`: a look goes to the warm pod's Service (`POST <warm_url>/look`, the page's address in `{"url": ...}`)
and the line it gets back is the picture. A pod that is busy, missing, unreachable, slow or broken (`browser`, no
picture) means the look is taken in a pod of its own; `not_ready` and `too_large` are the look's answer and are not
tried again."""

import asyncio
import json

import httpx2
import pytest
from ashley.looks.looker import LookUnavailable, Shot
from ashley.looks.warm_looker import WarmLooker
from warm_blind_support import (CONFIG, JPEG, PAGE_URL, TARGET, TOKEN, WARM_URL, FakeCold, FakeKube, failed_line, fields_of,
                               go, keeper, line_of, log_text, mock_client, text_reply, with_config)


def looker(cold: FakeCold, client: httpx2.AsyncClient) -> WarmLooker:
    return WarmLooker(cold, keeper(FakeKube()), client, WARM_URL, CONFIG)


def look(cold: FakeCold, client: httpx2.AsyncClient, name: str = "look-abc") -> Shot:
    return go(looker(cold, client).look(name, TARGET))


def test_a_look_goes_to_the_pod_and_its_picture_is_the_answer() -> None:
    cold = FakeCold()
    client, seen = mock_client(lambda r: text_reply(line_of(JPEG) + "\n"))
    assert look(cold, client) == Shot(JPEG)
    assert cold.asked == []
    assert len(seen) == 1


def test_it_posts_the_page_address_to_the_look_path_of_the_service() -> None:
    client, seen = mock_client(lambda r: text_reply(line_of(JPEG)))
    look(FakeCold(), client)
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == WARM_URL + "/look"
    assert json.loads(request.content) == {"url": PAGE_URL}


@pytest.mark.parametrize("reason", ["not_ready", "too_large"])
def test_an_answer_of_the_pod_is_the_look_s_and_is_not_tried_again(reason: str) -> None:
    cold = FakeCold()
    client, seen = mock_client(lambda r: text_reply(failed_line(reason)))
    with pytest.raises(LookUnavailable) as raised:
        look(cold, client)
    assert reason in str(raised.value)
    assert cold.asked == [] and len(seen) == 1


def test_a_busy_pod_sends_the_look_to_a_pod_of_its_own() -> None:
    cold = FakeCold(b"cold-picture")
    client, seen = mock_client(lambda r: text_reply("busy", status=503))
    assert look(cold, client, "look-xyz") == Shot(b"cold-picture")
    assert cold.asked == [("look-xyz", TARGET)]
    assert len(seen) == 1


@pytest.mark.parametrize("status", [400, 404, 405, 413, 500, 502, 504])
def test_a_pod_that_errors_sends_the_look_to_a_pod_of_its_own(status: int) -> None:
    cold = FakeCold()
    client, _ = mock_client(lambda r: text_reply("oops", status=status))
    assert look(cold, client) == Shot(b"cold-picture")
    assert len(cold.asked) == 1


@pytest.mark.parametrize("reason", ["browser", "no_picture", "something_new", ""])
def test_a_failure_that_is_not_an_answer_goes_to_a_pod_of_its_own(reason: str) -> None:
    cold = FakeCold()
    client, _ = mock_client(lambda r: text_reply(failed_line(reason)))
    assert look(cold, client) == Shot(b"cold-picture")
    assert len(cold.asked) == 1


@pytest.mark.parametrize("body", ["", "hello", "ashley-look ", "ashley-look !!!not base64!!!", "<html>502</html>", "\n"])
def test_a_reply_with_no_picture_goes_to_a_pod_of_its_own(body: str) -> None:
    cold = FakeCold()
    client, _ = mock_client(lambda r: text_reply(body))
    assert look(cold, client) == Shot(b"cold-picture")
    assert len(cold.asked) == 1


@pytest.mark.parametrize("error", [
    httpx2.ConnectError("no route"),
    httpx2.ConnectTimeout("slow"),
    httpx2.ReadTimeout("slower"),
    httpx2.RemoteProtocolError("hung up"),
    httpx2.ReadError("reset"),
    httpx2.WriteError("pipe"),
    httpx2.PoolTimeout("none free"),
])
def test_a_pod_that_cannot_be_reached_or_answers_too_slowly_sends_the_look_to_a_pod_of_its_own(error: Exception) -> None:
    cold = FakeCold()
    client, seen = mock_client(lambda r: error)
    assert look(cold, client) == Shot(b"cold-picture")
    assert len(cold.asked) == 1 and len(seen) == 1


def test_a_reply_that_is_not_text_goes_to_a_pod_of_its_own() -> None:
    cold = FakeCold()
    client, _ = mock_client(lambda r: httpx2.Response(200, content=b"\xff\xfe\x00garbage"))
    assert look(cold, client) == Shot(b"cold-picture")


def test_when_the_pod_of_its_own_fails_too_the_look_is_unavailable() -> None:
    cold = FakeCold("pod_never_ran")
    client, _ = mock_client(lambda r: text_reply("busy", status=503))
    with pytest.raises(LookUnavailable) as raised:
        look(cold, client)
    assert "pod_never_ran" in str(raised.value)
    assert len(cold.asked) == 1


def test_the_pod_of_its_own_is_asked_once() -> None:
    cold = FakeCold()
    client, seen = mock_client(lambda r: httpx2.ConnectError("no"))
    look(cold, client)
    assert len(cold.asked) == 1 and len(seen) == 1


def test_it_reaches_the_pod_within_warm_connect_s() -> None:
    client, seen = mock_client(lambda r: text_reply(line_of(JPEG)))
    look(FakeCold(), client)
    timeout = seen[0].extensions["timeout"]
    assert timeout["connect"] == CONFIG.warm_connect_s


def test_a_look_that_takes_as_long_as_a_page_may_is_not_cut_off() -> None:
    client, seen = mock_client(lambda r: text_reply(line_of(JPEG)))
    look(FakeCold(), client)
    read = seen[0].extensions["timeout"]["read"]
    assert read is None or read > CONFIG.ready_timeout_s


def test_it_renders() -> None:
    client, _ = mock_client(lambda r: text_reply(""))
    assert looker(FakeCold(draws=True), client).renders() is True


def test_a_cancelled_look_is_not_sent_to_a_pod_of_its_own() -> None:
    cold = FakeCold()
    started = asyncio.Event()

    class Hang(httpx2.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError

    pod = looker(cold, httpx2.AsyncClient(transport=Hang()))

    async def scenario() -> None:
        task = asyncio.create_task(pod.look("look-a", TARGET))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    go(scenario())
    assert cold.asked == []


def test_each_look_posts_its_own_page_address() -> None:
    client, seen = mock_client(lambda r: text_reply(line_of(JPEG)))
    pod = looker(FakeCold(), client)

    async def scenario() -> None:
        await pod.look("look-1", TARGET)
        await pod.look("look-2", TARGET)

    go(scenario())
    assert len(seen) == 2


def test_a_warm_look_is_logged_with_outcome_bytes_and_duration(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    client, _ = mock_client(lambda r: text_reply(line_of(JPEG)))
    look(FakeCold(), client)
    [event] = fields_of(caplog, "looks.warm")
    assert event["bytes"] == len(JPEG)
    assert event["outcome"] and isinstance(event["duration_ms"], int)
    assert not fields_of(caplog, "looks.warm_fallback")


def test_an_answer_is_logged_with_its_outcome(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    client, _ = mock_client(lambda r: text_reply(failed_line("not_ready")))
    with pytest.raises(LookUnavailable):
        look(FakeCold(), client)
    [event] = fields_of(caplog, "looks.warm")
    assert event["reason"] == "not_ready" and event["outcome"]


def test_a_fallback_is_logged_with_its_reason_and_the_reasons_tell_the_causes_apart(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    causes: list[httpx2.Response | Exception] = [text_reply("b", 503), httpx2.ConnectError("x"), httpx2.ReadTimeout("t"), text_reply(failed_line("browser"))]
    for cause in causes:
        client, _ = mock_client(lambda r, c=cause: c)
        look(FakeCold(), client)
    reasons = [str(f["reason"]) for f in fields_of(caplog, "looks.warm_fallback")]
    assert len(reasons) == 4 and all(reasons)
    assert len({reasons[0], reasons[1], reasons[2]}) == 3


def test_the_logs_never_carry_the_page_address_or_its_token(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG")
    cases: list[httpx2.Response | Exception] = [
        text_reply(line_of(JPEG)), text_reply(failed_line("not_ready")), text_reply("b", 503),
        httpx2.ConnectError(f"cannot connect for {PAGE_URL}"), httpx2.ReadTimeout(f"slow {PAGE_URL}"),
        text_reply(f"error at {PAGE_URL}", 500),
    ]
    for case in cases:
        client, _ = mock_client(lambda r, c=case: c)
        try:
            look(FakeCold(), client)
        except LookUnavailable:
            pass
    text = log_text(caplog)
    assert TOKEN not in text and PAGE_URL not in text


def test_the_wait_to_reach_the_pod_is_the_configured_one() -> None:
    client, seen = mock_client(lambda r: text_reply(line_of(JPEG)))
    pod = WarmLooker(FakeCold(), keeper(FakeKube()), client, WARM_URL, with_config(warm_connect_s=0.7))
    go(pod.look("look-a", TARGET))
    assert seen[0].extensions["timeout"]["connect"] == 0.7

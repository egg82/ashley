"""`key_check.answered`, the one read a model provider's kind makes before a key is stored, against an in-process
server: how each answer is classified, that the key goes in the request's headers, and that no redirect is followed.
The statuses are the ones each provider documents for a bad key (Gemini's 400 `API_KEY_INVALID`); none was captured."""

import asyncio

import httpx2
import pytest
from ashley.inference.key_check import answered

URL = "https://api.test/v1/models"


def asked(handler: httpx2.MockTransport) -> tuple[str | None, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler.handle_request(request)

    async def go() -> str | None:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(record)) as http:
            return await answered(http, URL, {"x-api-key": "sk-test"})
    return asyncio.run(go()), seen


def test_a_json_object_is_an_answer_and_the_key_is_sent_in_the_headers() -> None:
    got, seen = asked(httpx2.MockTransport(lambda r: httpx2.Response(200, json={"data": []})))
    assert got is None and seen[0].headers["x-api-key"] == "sk-test" and str(seen[0].url) == URL


@pytest.mark.parametrize("status", [400, 401, 403])
def test_a_refusal_status_is_key_refused(status: int) -> None:
    assert asked(httpx2.MockTransport(lambda r: httpx2.Response(status, json={"error": {}})))[0] == "key_refused"


@pytest.mark.parametrize("status", [404, 429, 500, 503])
def test_any_other_error_status_is_unreachable(status: int) -> None:
    assert asked(httpx2.MockTransport(lambda r: httpx2.Response(status, json={})))[0] == "unreachable"


def test_a_redirect_is_not_followed_and_is_unreachable() -> None:
    got, seen = asked(httpx2.MockTransport(
        lambda r: httpx2.Response(302, headers={"location": "https://elsewhere.test/"})))
    assert got == "unreachable" and len(seen) == 1


@pytest.mark.parametrize("body", [b"<html>hello</html>", b"[1, 2]"])
def test_a_success_that_is_not_a_json_object_is_the_wrong_service(body: bytes) -> None:
    assert asked(httpx2.MockTransport(lambda r: httpx2.Response(200, content=body)))[0] == "wrong_service"


def test_no_answer_is_unreachable() -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)
    assert asked(httpx2.MockTransport(fail))[0] == "unreachable"

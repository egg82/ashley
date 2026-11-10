"""The two image providers against what the real services answered (`image_captured/`, captured 2026-11-03 from
`gemini-3.1-flash-lite-image` and `gpt-image-2.5-flare`, the image bytes swapped for a few bytes) and an in-process
stand-in for the wire: the request each sends, the picture and usage read back, and how each failure is classified."""

import base64
import json

import httpx2
import pytest
from ashley.inference.gemini_image import GeminiImageMaker
from ashley.inference.image import Aspect
from ashley.inference.model import Usage
from ashley.inference.gemini_image import parse as gemini_parse
from ashley.inference.openai_image import OpenAIImageMaker
from ashley.inference.openai_image import parse as openai_parse
from ashley.inference.provider import ProviderFailed, ProviderRefused
from image_support import JPEG, captured
from speech_support import run


def gemini(status: int, body: object) -> tuple[GeminiImageMaker, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(status, json=body)

    client = httpx2.AsyncClient(base_url="https://gem.test", headers={"x-goog-api-key": "k"},
                                transport=httpx2.MockTransport(handle))
    return GeminiImageMaker("gemini_image", client), seen


def openai(status: int, body: object) -> tuple[OpenAIImageMaker, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(status, json=body)

    client = httpx2.AsyncClient(base_url="https://oai.test", headers={"Authorization": "Bearer k"},
                                transport=httpx2.MockTransport(handle))
    return OpenAIImageMaker("openai_image", client), seen


def test_a_gemini_response_gives_its_image_type_bytes_and_usage() -> None:
    made = gemini_parse(captured("gemini_drawn.json"))
    assert (made.media_type, made.data) == ("image/jpeg", JPEG)
    assert made.usage == Usage(6, 1479)


def test_an_openai_response_gives_the_bytes_the_asked_type_and_usage() -> None:
    made = openai_parse(captured("openai_drawn.json"), "image/jpeg")
    assert (made.media_type, made.data) == ("image/jpeg", JPEG)
    assert made.usage == Usage(12, 196)


def test_gemini_asks_for_an_image_only_in_the_aspects_ratio_with_its_key_in_a_header() -> None:
    maker, seen = gemini(200, captured("gemini_drawn.json"))
    run(maker.make("gemini-3.1-flash-lite-image", {}, "a lamp", "wide", 5.0))
    request = seen[0]
    assert (request.method, request.url.path) == ("POST", "/v1beta/models/gemini-3.1-flash-lite-image:generateContent")
    assert request.headers["x-goog-api-key"] == "k"
    assert json.loads(request.content) == {
        "contents": [{"parts": [{"text": "a lamp"}]}],
        "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "3:2"}}}


@pytest.mark.parametrize(("aspect", "size"), [("square", "1024x1024"), ("wide", "1536x1024"), ("tall", "1024x1536")])
def test_openai_asks_for_one_picture_of_the_aspects_size_and_the_routes_quality_and_format(aspect: Aspect,
                                                                                           size: str) -> None:
    maker, seen = openai(200, captured("openai_drawn.json"))
    made = run(maker.make("gpt-image-2.5-flare", {"quality": "low", "output_format": "png"}, "a lamp", aspect, 5.0))
    request = seen[0]
    assert (request.method, request.url.path) == ("POST", "/v1/images/generations")
    assert json.loads(request.content) == {"model": "gpt-image-2.5-flare", "prompt": "a lamp", "n": 1, "size": size,
                                           "output_format": "png", "quality": "low"}
    assert made.media_type == "image/png"


def test_a_prompt_blocked_or_a_candidate_with_no_image_is_a_refusal_with_the_usage_billed() -> None:
    with pytest.raises(ProviderRefused) as blocked:
        gemini_parse(captured("gemini_prompt_blocked.json"))
    assert blocked.value.usage is not None and blocked.value.usage.output_tokens == 0
    no_image: dict[str, object] = {"candidates": [{"content": {}, "finishReason": "NO_IMAGE", "index": 0}],
                                   "usageMetadata": {"promptTokenCount": 13, "totalTokenCount": 13}}
    with pytest.raises(ProviderRefused):
        gemini_parse(no_image)


def test_openais_moderation_block_is_a_refusal_and_any_other_400_is_an_error() -> None:
    maker, _ = openai(400, captured("openai_moderation_blocked.json"))
    with pytest.raises(ProviderRefused):
        run(maker.make("m", {}, "x", "square", 5.0))
    maker, _ = openai(400, captured("openai_bad_size.json"))
    with pytest.raises(ProviderFailed) as bad:
        run(maker.make("m", {}, "x", "square", 5.0))
    assert bad.value.failure == "error"


@pytest.mark.parametrize(("status", "failure"), [(401, "unavailable"), (402, "unavailable"), (429, "unavailable"),
                                                 (503, "unavailable"), (404, "error"), (400, "error")])
def test_an_http_failure_is_classified_by_its_status(status: int, failure: str) -> None:
    for maker in (gemini(status, {"error": {}})[0], openai(status, {"error": {}})[0]):
        with pytest.raises(ProviderFailed) as e:
            run(maker.make("m", {}, "x", "square", 5.0))
        assert e.value.failure == failure


def test_a_connection_failure_is_unavailable() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down")

    client = httpx2.AsyncClient(base_url="https://x.test", transport=httpx2.MockTransport(refuse))
    with pytest.raises(ProviderFailed) as e:
        run(OpenAIImageMaker("o", client).make("m", {}, "x", "square", 5.0))
    assert e.value.failure == "unavailable"


NO_GEMINI_IMAGE: list[object] = [None, [], {}, {"candidates": []}, {"candidates": [{"content": {"parts": []},
                                                                                        "finishReason": "STOP"}]},
                                  {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/jpeg",
                                                                                          "data": "%%%"}}]}}]},
                                  {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/jpeg",
                                                                                          "data": ""}}]}}]}]


@pytest.mark.parametrize("body", NO_GEMINI_IMAGE)
def test_a_gemini_response_without_a_usable_image_fails_invalid_output(body: object) -> None:
    with pytest.raises(ProviderFailed) as e:
        gemini_parse(body)
    assert e.value.failure == "invalid_output"


NO_OPENAI_IMAGE: list[object] = [None, {}, {"data": []}, {"data": [{}]}, {"data": [{"b64_json": "%%%"}]},
                                 {"data": [{"b64_json": ""}]}]


@pytest.mark.parametrize("body", NO_OPENAI_IMAGE)
def test_an_openai_response_without_a_usable_image_fails_invalid_output(body: object) -> None:
    with pytest.raises(ProviderFailed) as e:
        openai_parse(body, "image/jpeg")
    assert e.value.failure == "invalid_output"


def test_each_provider_rejects_the_params_it_does_not_take() -> None:
    gemini(200, {})[0].check_image_params({})
    with pytest.raises(ValueError, match="quality"):
        gemini(200, {})[0].check_image_params({"quality": "low"})
    openai(200, {})[0].check_image_params({"quality": "high", "output_format": "webp"})
    for bad in ({"size": "1x1"}, {"quality": "ultra"}, {"output_format": "gif"}):
        with pytest.raises(ValueError):
            openai(200, {})[0].check_image_params(bad)


def test_the_encoded_picture_round_trips() -> None:
    assert base64.b64decode(captured("openai_drawn.json")["data"][0]["b64_json"]) == JPEG

"""`GeminiImageMaker`: pictures from Gemini's native `generateContent` (the OpenAI-compatible endpoint chat uses does
not draw with these models). It takes a configured `httpx2.AsyncClient` (base URL
`https://generativelanguage.googleapis.com`, `x-goog-api-key` header), so a test can point it at a stand-in server.

Route `model` is the image model (`gemini-3.1-flash-lite-image`); it takes no params. The request asks for an image
part only, in the aspect's ratio. A 200 whose `promptFeedback.blockReason` is set, or whose candidate ends without an
image for a safety `finishReason`, is a refusal; one with no image for any other reason fails `invalid_output`.
A timeout, connection failure, 408, 409, 429, 5xx, 401, 402 or 403 fails `unavailable`, any other status `error`.
Usage is the prompt's tokens and the candidate's: the image is most of them, and `prices.json` prices them all at the
image rate, so a cost here is an upper bound."""

import base64
import binascii
from collections.abc import Mapping

import httpx2

from .image import Aspect
from .image_http import count, items, obj, post_json
from .image_provider import ImageMaker, Made
from .model import Usage
from .provider import ProviderFailed, ProviderRefused, status_failure

_RATIO: dict[Aspect, str] = {"square": "1:1", "wide": "3:2", "tall": "2:3"}
_REFUSING = frozenset({"NO_IMAGE", "SAFETY", "IMAGE_SAFETY", "PROHIBITED_CONTENT", "IMAGE_PROHIBITED_CONTENT",
                       "BLOCKLIST", "SPII"})


class GeminiImageMaker(ImageMaker):
    def __init__(self, name: str, client: httpx2.AsyncClient) -> None:
        self._name = name
        self._client = client

    @property
    def name(self) -> str:
        return self._name

    def check_image_params(self, params: Mapping[str, object]) -> None:
        if params:
            raise ValueError(f"unknown parameter {sorted(params)[0]!r}")

    async def make(self, model: str, params: Mapping[str, object], prompt: str, aspect: Aspect,
                   timeout_s: float) -> Made:
        status, body = await post_json(
            self._client, f"/v1beta/models/{model}:generateContent",
            {"contents": [{"parts": [{"text": prompt}]}],
             "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": _RATIO[aspect]}}},
            timeout_s)
        if status >= 400:
            raise ProviderFailed(status_failure(status), f"HTTP status={status}")
        return parse(body)


def parse(body: object) -> Made:
    """The picture in a `generateContent` response. Raises ProviderRefused or ProviderFailed as the module says."""
    top = obj(body)
    if top is None:
        raise ProviderFailed("invalid_output", "the response is not a JSON object")
    meta = obj(top.get("usageMetadata"))
    usage = None if meta is None else Usage(count(meta.get("promptTokenCount")), count(meta.get("candidatesTokenCount")))
    feedback = obj(top.get("promptFeedback"))
    if feedback is not None and feedback.get("blockReason"):
        raise ProviderRefused(f"blocked: {feedback['blockReason']}", usage)
    candidates = items(top.get("candidates"))
    candidate = obj(candidates[0]) if candidates else None
    if candidate is None:
        raise ProviderFailed("invalid_output", "the response held no candidate", usage)
    for part in items((obj(candidate.get("content")) or {}).get("parts")):
        inline = obj((obj(part) or {}).get("inlineData"))
        data, media = (inline or {}).get("data"), (inline or {}).get("mimeType")
        if isinstance(data, str) and isinstance(media, str) and media.startswith("image/"):
            return Made(_decoded(data, usage), media, usage)
    reason = candidate.get("finishReason")
    if reason in _REFUSING:
        raise ProviderRefused(f"finishReason {reason}", usage)
    raise ProviderFailed("invalid_output", f"the response held no image (finishReason {reason})", usage)


def _decoded(data: str, usage: Usage | None) -> bytes:
    try:
        picture = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ProviderFailed("invalid_output", "the image is not valid base64", usage) from e
    if not picture:
        raise ProviderFailed("invalid_output", "the image is empty", usage)
    return picture

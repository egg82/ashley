"""`OpenAIImageMaker`: pictures from OpenAI's `POST /v1/images/generations`. It takes a configured
`httpx2.AsyncClient` (base URL `https://api.openai.com`, bearer `Authorization` header), so a test can point it at a
stand-in server.

Route `model` is the image model (`gpt-image-2.5-flare`). Params: `quality` (`low`, `medium`, `high`; optional) and
`output_format` (`jpeg`, `png`, `webp`; default `jpeg`). The aspect picks the size: 1024x1024, 1536x1024 or 1024x1536.
A 400 whose error code is `moderation_blocked` is a refusal; an empty `data` fails `invalid_output`. A timeout,
connection failure, 408, 409, 429, 5xx, 401, 402 or 403 fails `unavailable`, any other status `error`."""

import base64
import binascii
from collections.abc import Mapping

import httpx2

from .image import Aspect
from .image_http import count, items, obj, post_json
from .image_provider import ImageMaker, Made
from .model import Usage
from .provider import ProviderFailed, ProviderRefused, status_failure

_SIZE: dict[Aspect, str] = {"square": "1024x1024", "wide": "1536x1024", "tall": "1024x1536"}
_QUALITY = ("low", "medium", "high")
_FORMAT = ("jpeg", "png", "webp")


class OpenAIImageMaker(ImageMaker):
    def __init__(self, name: str, client: httpx2.AsyncClient) -> None:
        self._name = name
        self._client = client

    @property
    def name(self) -> str:
        return self._name

    def check_image_params(self, params: Mapping[str, object]) -> None:
        unknown = sorted(set(params) - {"quality", "output_format"})
        if unknown:
            raise ValueError(f"unknown parameter {unknown[0]!r}")
        if "quality" in params and params["quality"] not in _QUALITY:
            raise ValueError(f"quality must be one of {', '.join(_QUALITY)}")
        if "output_format" in params and params["output_format"] not in _FORMAT:
            raise ValueError(f"output_format must be one of {', '.join(_FORMAT)}")

    async def make(self, model: str, params: Mapping[str, object], prompt: str, aspect: Aspect,
                   timeout_s: float) -> Made:
        output_format = str(params.get("output_format", "jpeg"))
        request: dict[str, object] = {"model": model, "prompt": prompt, "n": 1, "size": _SIZE[aspect],
                                      "output_format": output_format}
        if "quality" in params:
            request["quality"] = params["quality"]
        status, body = await post_json(self._client, "/v1/images/generations", request, timeout_s)
        if status >= 400:
            if status == 400 and _code(body) == "moderation_blocked":
                raise ProviderRefused("moderation_blocked")
            raise ProviderFailed(status_failure(status), f"HTTP status={status}")
        return parse(body, f"image/{output_format}")


def _code(body: object) -> object:
    return (obj((obj(body) or {}).get("error")) or {}).get("code")


def parse(body: object, media_type: str) -> Made:
    """The picture in an images response, of `media_type`. Raises ProviderFailed `invalid_output` when there is none."""
    top = obj(body)
    if top is None:
        raise ProviderFailed("invalid_output", "the response is not a JSON object")
    meta = obj(top.get("usage"))
    usage = None if meta is None else Usage(count(meta.get("input_tokens")), count(meta.get("output_tokens")))
    data = items(top.get("data"))
    encoded = (obj(data[0]) or {}).get("b64_json") if data else None
    if not isinstance(encoded, str):
        raise ProviderFailed("invalid_output", "the response held no image", usage)
    try:
        picture = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ProviderFailed("invalid_output", "the image is not valid base64", usage) from e
    if not picture:
        raise ProviderFailed("invalid_output", "the image is empty", usage)
    return Made(picture, media_type, usage)

"""Her tool for a picture she has drawn (`bench_make_image`), offered on a bench's talk while an object store is wired:
the prompt she writes goes to an image model (`Inference.make_image`), and the picture it draws is kept and added as an
ordinary `image` piece (`workshop.bench_file`), so it is shown, looked at, downloadable and undoable like an upload.
Each picture costs money, so a household has a limit per window (`inference.image_quota`).

Outcomes: `capped` (the household is at its limit), `refused` (the image model's safety system declined the prompt;
no other model is asked), `unavailable` (no model drew one, or the bench or its storage cannot be reached), `too_large`
and `bad_image` (the bytes a model returned are not taken). The `tools.call` line carries the outcome, the bench, the
piece, provider, model, media type and size; never the prompt."""

import time
from collections.abc import Mapping
from typing import get_args

from .. import services
from ..files.intake import Refused as FileRefused
from ..files.store import NullStore, ObjectStore, StoreUnavailable
from ..inference.image import Aspect
from ..inference.inference import (ImageCapped, ImageUnavailable, Inference, InferenceRefused, InferenceUnavailable,
                                   NullInference)
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..workshop import bench_file
from ..workshop import rules as workshop_rules
from ..workshop.model import Owner
from ..workshop.workshop import BenchClosed, BenchNotFound, WorkshopUnavailable
from . import bench_results
from .tainted import her
from .bench_args import BadArguments, check_names
from .tools import Catalogue, Tools

RULES = workshop_rules.load()
MAKE = "bench_make_image"
NAME_CHARS = 80
ASPECTS: tuple[str, ...] = get_args(Aspect)
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
INSTRUCTIONS = ("bench_make_image draws a picture from a prompt you write and adds it to the bench as an image piece; "
                "every picture costs money and a household has a limit on how many it may have drawn, so draw one when the person asked for "
                "a picture or one would clearly help, and look at it with bench_look before you describe it.")
SPEC = ToolSpec(MAKE, "Draw a picture from `prompt`, which describes what it shows, and add it to this bench, last, as an "
                "image piece. `aspect` is square (the default), wide or tall. `name` titles the piece, without an "
                "extension. Each picture costs money and the household's limit on pictures applies. An image model may "
                "decline a prompt, and then nothing is added.",
                {"type": "object", "properties": {
                    "prompt": {"type": "string"}, "aspect": {"type": "string", "enum": list(ASPECTS)},
                    "name": {"type": "string"}}, "required": ["prompt"]}, outside=False, tier="runs")
HINTS = {
    "capped": "the household has had as many pictures drawn as its limit allows for now; tell the person, and do not try again "
              "soon",
    "refused": "the image model declined that prompt; tell the person it was declined, and do not retry it reworded to "
               "get around that",
    "unavailable": "no image model could draw it right now, or the bench or its storage cannot be reached; nothing was added",
    "too_large": "the picture is larger than a bench takes",
    "bad_image": "what the image model returned was not a picture a bench takes"}
_FILE_REFUSALS = {"empty": "bad_image", "type_not_allowed": "bad_image", "type_mismatch": "bad_image",
                  "too_large": "too_large"}


class BenchImageTools(Tools):
    def __init__(self, household_id: int, person_id: int, bench_id: int, conversation_id: int) -> None:
        self._owner = Owner(household_id, person_id)
        self._bench = bench_id
        self._conversation = conversation_id

    async def catalogue(self) -> Catalogue:
        """Empty when no object store is wired or the process draws nothing."""
        if isinstance(services.get(ObjectStore), NullStore) or isinstance(services.get(Inference), NullInference):
            return Catalogue((), None)
        return Catalogue((SPEC,), INSTRUCTIONS)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises for what the bench, the store or the image model did: each is an error result, logged
        `tools.call`."""
        started = time.monotonic()
        if call.name != MAKE:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            check_names(call.arguments, SPEC)
            return await self._make(call, started)
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e), bench=self._bench)
        except ImageCapped:
            return self._failed(call, started, "capped")
        except InferenceRefused:
            return self._failed(call, started, "refused")
        except ImageUnavailable as e:
            kinds = ", ".join(sorted(set(e.failures))) or "none was reachable"
            return bench_results.failed(call, started, "unavailable", f"{HINTS['unavailable']} (failure: {kinds})",
                                        bench=self._bench)
        except (InferenceUnavailable, WorkshopUnavailable, StoreUnavailable):
            return self._failed(call, started, "unavailable")
        except FileRefused as e:
            return self._failed(call, started, _FILE_REFUSALS[e.reason])
        except BenchNotFound:
            return bench_results.failed(call, started, "not_found", "this bench is gone", bench=self._bench)
        except BenchClosed:
            return bench_results.failed(call, started, "closed", "this bench is closed and takes no change",
                                        bench=self._bench)

    def _failed(self, call: ToolCall, started: float, outcome: str) -> ToolResult:
        return bench_results.failed(call, started, outcome, HINTS[outcome], bench=self._bench)

    async def _make(self, call: ToolCall, started: float) -> ToolResult:
        prompt, aspect, name = _prompt(call.arguments), _aspect(call.arguments), _name(call.arguments)
        drawn = await services.get(Inference).make_image(
            prompt, aspect, household_id=self._owner.household_id, conversation_id=self._conversation)
        extension = EXTENSIONS.get(drawn.media_type, "img")
        stored, applied = await bench_file.add_file(self._owner, self._bench, her(), drawn.data, f"{name}.{extension}",
                                                    drawn.media_type, RULES)
        if applied.outcome != "accepted":
            return bench_results.failed(call, started, applied.outcome, bench_results.HINTS[applied.outcome],
                                        bench=self._bench, command="add", seq=applied.seq)
        return bench_results.ok(call, started, {"seq": applied.seq, "piece_id": applied.piece_id,
                                                 "media_type": stored.media_type, "size": stored.size},
                                bench=self._bench, command="add", seq=applied.seq, piece=applied.piece_id,
                                provider=drawn.provider, model=drawn.model, media_type=stored.media_type,
                                size=stored.size)


def _prompt(args: Mapping[str, object]) -> str:
    prompt = args.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise BadArguments("prompt is a non-empty string")
    return prompt.strip()


def _aspect(args: Mapping[str, object]) -> Aspect:
    aspect = args.get("aspect", "square")
    for known in get_args(Aspect):
        if aspect == known:
            return known
    raise BadArguments("aspect is one of " + ", ".join(ASPECTS))


def _name(args: Mapping[str, object]) -> str:
    name = args.get("name", "picture")
    if not isinstance(name, str):
        raise BadArguments("name is a string")
    return name.strip()[:NAME_CHARS] or "picture"

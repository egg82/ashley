"""The Inference service (`ashley.services`): one structured reply, transcript, spoken text or embedding from
whichever model is configured for this task and reachable now. Callers import only this module, `model`, `reply` and `speech`;
providers, routing and the spend ledger live beside it.

Prompts, replies, audio and transcripts are never logged; every call, answered or not, is recorded in the spend
ledger by task, provider and model."""

from abc import abstractmethod
from collections.abc import Sequence
from typing import TypeVar

from pydantic import BaseModel

from ..services import Service
from .embedding import EmbedRole, Embedded, EmbedTask
from .image import Aspect, Imaged
from .provider import Failure
from .model import Prompt, Task, ToolCalls
from .speech import AudioFormat, Heard, Speech, SpeechTask, Transcript
from .voiceprint import Voiceprint, VoiceprintTask

T = TypeVar("T", bound=BaseModel)


class InferenceError(Exception):
    """Base of what the service raises on purpose."""


class InferenceUnavailable(InferenceError):
    """No route for the task produced an answer: each was unwired, resting after a recent failure, or failed now.
    Transient: the caller may retry later."""


class InferenceCutOff(InferenceUnavailable):
    """No route answered and at least one reply was cut off at the token limit (`ProviderFailed.cut_off`): asking
    again for something smaller may work. A kind of InferenceUnavailable, so a caller that does not tell it apart
    treats it as one."""


class InferenceRejected(InferenceUnavailable):
    """Every route called rejected the request itself (a provider's 4xx that is not about the account, outcome `error`),
    so asking again replays the same failure. A kind of InferenceUnavailable, so a caller that only degrades on a
    model out of reach still does; one that would retry or say it cannot be reached tells this apart first."""


class ImageUnavailable(InferenceUnavailable):
    """No route drew the picture. `failures` is why each route that was called failed (`provider.Failure`, in route
    order); empty when every route was unwired or resting."""

    def __init__(self, failures: tuple[Failure, ...]) -> None:
        super().__init__("no route answered for task image" + (f" ({', '.join(failures)})" if failures else ""))
        self.failures = failures


class ImageCapped(InferenceError):
    """The household has had as many pictures drawn in the window as its limit allows (`image_quota`); nothing was
    called. Not transient within the window."""

    def __init__(self, limit: int, window_s: int) -> None:
        super().__init__(f"{limit} pictures in {window_s} seconds")
        self.limit = limit
        self.window_s = window_s


class InferenceRefused(InferenceError):
    """The model on the route that answered declined to. No other route was tried."""


class Inference(Service):
    @classmethod
    def null(cls) -> "Inference":
        return NullInference()

    @abstractmethod
    async def generate(self, task: Task, prompt: Prompt, output: type[T], *, conversation_id: int | None = None) -> T:
        """One reply shaped as `output` (usually `reply.Reply`), validated.

        Tries the task's routes in their configured order. A route is skipped when its provider is not wired or is
        resting: a provider rests for the configured `cooldown_s` after a call to it fails `unavailable`, so a spent or
        unreachable account adds no failing call before each good one. Each route that is called sends
        `prompt.system_for(route.variant)`. The first valid reply is returned; a call that fails moves on to the next
        route; a refusal raises InferenceRefused at once.

        Every call made is one row in the spend ledger: task, provider, model, conversation, outcome (`ok`, `refused`, or
        the `provider.Failure`), tokens, cost in USD where the model has a price and NULL where it has none, and duration.
        A ledger write that fails is logged `inference.spend_unrecorded` and does not cost the caller the reply.

        `conversation_id` is the conversation the call serves, recorded on each spend row (None: it serves none). Its
        household's routes are the ones walked: a model the household chose for the task comes first, the deployment's
        routes after it (`household_routes`); a call serving no conversation walks the deployment's.

        Raises ValueError (before calling anything) for a task outside `Task`, or a prompt carrying `tools` (that is
        `step`); InferenceRefused; InferenceUnavailable when no route answered. Logs `inference.call` per call made
        (task, provider, model, outcome, tokens, duration_ms) and `inference.route_skipped` per route skipped (task,
        provider, model, reason `unwired`, `resting` or `no_tool_calls`). The cost is the model catalogue's
        (`catalogue.ModelCatalogue`)."""

    @abstractmethod
    async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                   conversation_id: int | None = None) -> T | ToolCalls:
        """One model call of a tool-using loop: either the reply shaped as `output`, or the tools the model asked for
        instead, which the caller runs and sends back as `ToolResults` after this `ToolCalls` in its next prompt. The
        caller owns the loop and its limit; under `tool_choice` `none` the answer is always a reply.

        Everything else is `generate`'s contract: routes in order, skips, resting, refusal final, one spend row and one
        `inference.call` per call made, with outcome `ok` for a call that returned tool calls. A route that answers
        with tool calls answers the step; the next step starts again from the first route, so one loop may be carried
        by more than one provider. Tool calls naming a tool not in `prompt.tools`, or repeating an id, fail that call
        `invalid_output`. A prompt with no tools is allowed, and then always gets a reply; one with tools for a task in
        `model.TOOLLESS` raises ValueError before calling anything. A prompt with tools skips each
        route whose model the catalogue lists without tool calls (reason `no_tool_calls`). Tool names, arguments and
        results are never logged; `inference.call` adds `tool_calls`, the number asked for (0 for a reply)."""

    @abstractmethod
    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        """The words in `heard`, from the first of the task's routes that answers.

        The first route is fed chunks as they arrive (a streaming provider decodes while the person is still talking,
        so little is left after they stop); a provider that needs the whole utterance gets it when the chunks end.
        When a route fails, the next is given the whole utterance read so far plus the rest, so falling back loses no
        audio. Returns after the chunks have ended.

        Routes, skips, resting and the spend ledger are `generate`'s, per call made (`conversation_id` as there): a route whose provider cannot
        transcribe is a configuration error caught when the routes load, not a skip. A transcript that is empty is an
        answer (nothing was said), not a failure. The spend row's usage carries `audio_ms`, the utterance's duration.

        Raises ValueError (before calling anything) for a task other than `transcribe`; InferenceUnavailable when no
        route answered. Logs `inference.call` per call made with `audio_ms` in place of tokens."""

    @abstractmethod
    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        """Her voice saying `text` (non-empty, already in the spellings the voice should say), from the first of the
        task's routes whose provider starts answering; the route's params pick the voice.

        Returns once the provider has accepted the request and its first bytes are ready, so a route that fails before
        that moves on to the next; a failure after audio has started ends the stream early (the caller hears a cut-off
        reply, not another voice) and is recorded as that route's failure. One spend row per call made (with `conversation_id`
        as `generate`'s), written when its stream ends or fails, with `characters`, the length of `text`, as usage.

        Raises ValueError (before calling anything) for a task other than `speak` or an empty `text`;
        InferenceUnavailable when no route started. Logs `inference.call` per call made with `characters`."""

    async def embed(self, texts: Sequence[str], role: EmbedRole, *, conversation_id: int | None = None) -> Embedded:
        """One unit-length vector per text, in order, made as `role` (`EmbedRole`) by the first of the `embed` task's
        routes that answers; the vectors' `model` names the route. Routes, skips, resting and the spend ledger are
        `generate`'s, per call made (`conversation_id` as there): the usage is `characters`, the total length of
        `texts`, and a model that runs locally costs 0 (`providers.json`'s `local` kind). A call is one batch: every
        text is embedded together or none is.

        Raises ValueError (before calling anything) for no texts or a blank text; InferenceUnavailable when no route
        answered, including when the task has no routes wired. Logs `inference.call` per call made with `texts`, `role`
        and `characters`; the texts and vectors are never logged. This default answers nothing, as `NullInference`
        does, so a stand-in that never embeds need not implement it."""
        raise InferenceUnavailable("Inference does not embed")

    async def voiceprint(self, format: AudioFormat, pcm: bytes, *, conversation_id: int | None = None) -> Voiceprint:
        """How the voice in one whole utterance (`pcm`, raw PCM in `format`) sounds, by the first of the `voiceprint`
        task's routes that answers; the print's `model` names the route and `audio_ms` the utterance's duration.
        Routes, skips, resting and the spend ledger are `generate`'s, per call made (`conversation_id` as there):
        the usage is `audio_ms`, and a model that runs locally costs 0 (`providers.json`'s `local` kind).

        Raises ValueError (before calling anything) for empty `pcm` or a length that is not a whole number of
        frames; InferenceUnavailable when no route answered, including when the task has no routes wired. Logs
        `inference.call` per call made with `audio_ms`; the audio and the vector are never logged. This default
        answers nothing, as `NullInference` does, so a stand-in that never makes prints need not implement it."""
        raise InferenceUnavailable("Inference does not make voiceprints")

    async def make_image(self, prompt: str, aspect: Aspect, *, household_id: int, conversation_id: int) -> Imaged:
        """A picture of `prompt` (non-blank) in `aspect` for `household_id`, asked for in `conversation_id`, from the
        first of the `image` task's routes that answers. First the household's count of pictures in the window is
        checked against its limit (`image_quota`), and a household at it, or a service with no limit wired, raises
        ImageCapped before any provider is called. Routes, skips, resting and the spend ledger are `generate`'s, per
        call made: the
        usage is the provider's tokens, and the cost is the catalogue's for the model. A provider's safety stop raises
        InferenceRefused at once, as for text: the prompt is not offered to another route. The prompt and the picture
        are never logged; `inference.call` carries `aspect` and, for a picture, `bytes`.

        Raises ValueError (before calling anything) for a blank prompt; ImageCapped; InferenceRefused; ImageUnavailable (an
        InferenceUnavailable) when no route drew one. This default answers nothing, as `NullInference` does."""
        raise InferenceUnavailable("Inference does not draw")

    async def warm(self, task: SpeechTask | EmbedTask | VoiceprintTask) -> None:
        """Prepare the route `speak`, `embed` or `voiceprint` would try first now (its provider's `warm`: an open connection, a
        loaded model), so a call soon after starts sooner. Nothing is billed and no spend row is written. Best
        effort: returns when done or failed and never raises, except ValueError (before anything) for any other task.
        Logs `inference.warm` (task, provider, model, outcome `ok` or the failure, duration_ms) when a route was
        warmed. This default prepares nothing."""
        if task not in ("speak", "embed", "voiceprint"):
            raise ValueError(f"only speak, embed and voiceprint are warmed: {task!r}")


class NullInference(Inference):
    """Answers nothing: what an unwired process sees. Every call raises InferenceUnavailable, so a missing
    registration fails loudly instead of inventing a reply."""

    async def generate(self, task: Task, prompt: Prompt, output: type[T], *, conversation_id: int | None = None) -> T:
        raise InferenceUnavailable("Inference is not wired")

    async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                   conversation_id: int | None = None) -> T | ToolCalls:
        raise InferenceUnavailable("Inference is not wired")

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise InferenceUnavailable("Inference is not wired")

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise InferenceUnavailable("Inference is not wired")

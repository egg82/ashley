"""The image half of `RoutedInference`: the task's routes in order, each call recorded in the spend ledger. Contract:
`Inference.make_image`."""

from .image import Aspect, Imaged, ImageTask
from .image_provider import ImageMaker
from .image_quota import ImageCap
from .inference import ImageCapped, ImageUnavailable, InferenceRefused
from .provider import Failure, ProviderFailed, ProviderRefused
from .roster import Roster

TASK: ImageTask = "image"


class ImageCalls:
    def __init__(self, roster: Roster, cap: ImageCap | None) -> None:
        self._roster = roster
        self._cap = cap

    async def make(self, prompt: str, aspect: Aspect, household_id: int, conversation_id: int) -> Imaged:
        if not prompt.strip():
            raise ValueError("make_image takes a non-blank prompt")
        if self._cap is None:
            raise ImageCapped(0, 0)
        await self._cap.check(household_id)
        failures: list[Failure] = []
        for route, provider in self._roster.candidates(TASK, ImageMaker):
            started = self._roster.clock()
            fields: dict[str, object] = {"aspect": aspect}
            try:
                made = await provider.make(route.model, route.params, prompt, aspect, route.timeout_s)
            except ProviderRefused as e:
                await self._roster.record(TASK, route, "refused", e.usage, started, fields, conversation_id, str(e))
                raise InferenceRefused(f"{route.provider} declined to draw") from e
            except ProviderFailed as e:
                await self._roster.record(TASK, route, e.failure, e.usage, started, fields, conversation_id, str(e))
                self._roster.failed(route, e.failure)
                failures.append(e.failure)
                continue
            await self._roster.record(TASK, route, "ok", made.usage, started, {**fields, "bytes": len(made.data)},
                                      conversation_id)
            return Imaged(made.data, made.media_type, route.provider, route.model)
        raise ImageUnavailable(tuple(failures))

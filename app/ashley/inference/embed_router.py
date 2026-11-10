"""The embedding half of `RoutedInference`: the task's routes in order, each call recorded in the spend ledger.
Contract: `Inference.embed`."""

from collections.abc import Sequence

from .embed_provider import Embedder
from .embedding import EmbedRole, Embedded, EmbedTask
from .inference import InferenceUnavailable
from .model import Usage
from .provider import ProviderFailed
from .roster import Roster

TASK: EmbedTask = "embed"


class EmbedCalls:
    def __init__(self, roster: Roster) -> None:
        self._roster = roster

    async def warm(self) -> None:
        for route, provider in self._roster.candidates(TASK, Embedder):
            await self._roster.warm(TASK, route, provider.warm(route.model, route.params, route.timeout_s))
            return

    async def embed(self, texts: Sequence[str], role: EmbedRole, conversation_id: int | None) -> Embedded:
        if not texts or not all(t.strip() for t in texts):
            raise ValueError("embed takes at least one text, none of them blank")
        usage = Usage(0, 0, characters=sum(len(t) for t in texts))
        fields = {"texts": len(texts), "role": role, "characters": usage.characters}
        for route, provider in self._roster.candidates(TASK, Embedder):
            started = self._roster.clock()
            try:
                vectors = await provider.embed(route.model, route.params, texts, role, route.timeout_s)
            except ProviderFailed as e:
                await self._roster.record(TASK, route, e.failure, usage, started, fields, conversation_id,
                                          str(e))
                self._roster.failed(route, e.failure)
                continue
            await self._roster.record(TASK, route, "ok", usage, started, fields, conversation_id)
            return Embedded(tuple(tuple(v) for v in vectors), route.model)
        raise InferenceUnavailable(f"no route answered for task {TASK}")

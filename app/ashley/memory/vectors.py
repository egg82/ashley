"""Embedding for memory: `Inference.embed` as `PostgresMemory` needs it, where an embedder that cannot answer costs the
caller its vectors and never its work."""

import logging
from collections.abc import Sequence

from .. import logs, services
from ..inference.embedding import EmbedRole
from ..inference.inference import Inference, InferenceUnavailable
from .postgres_queries import Vector

log = logging.getLogger("ashley.memory")


class Vectors:
    """`model` is the model that made the vectors most recently returned, None before the first; the facts to embed
    again are those made by any other."""

    def __init__(self) -> None:
        self.model: str | None = None

    async def of(self, texts: Sequence[str], role: EmbedRole,
                 conversation_id: int | None = None) -> list[Vector] | None:
        """One `Vector` per text, in order, or None when `texts` is empty or has a blank text, or Inference could not
        embed (logged `memory.embed_unavailable`, with `role` and the number of texts). `conversation_id` is the
        conversation the embedding serves, for the spend row: a recall does not know it, a write and the write job's
        candidates do."""
        if not texts or not all(t.strip() for t in texts):
            return None
        try:
            embedded = await services.get(Inference).embed(texts, role, conversation_id=conversation_id)
        except InferenceUnavailable:
            logs.warning(log, "memory.embed_unavailable", role=role, texts=len(texts))
            return None
        self.model = embedded.model
        return [Vector(v, embedded.model) for v in embedded.vectors]

    async def one(self, text: str, role: EmbedRole, conversation_id: int | None = None) -> Vector | None:
        """`of` for a single text."""
        found = await self.of([text], role, conversation_id)
        return None if found is None else found[0]

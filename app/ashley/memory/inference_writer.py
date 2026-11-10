"""The `FactWriter` that asks a model: one `memory_write` call through `Inference`, its typed output checked and
converted in code (`writer_output`). People's names come from `People`, since the conversation carries only ids.

Logs `memory.write` per decision: conversation id, known facts, ops kept by kind, ops dropped by reason, facts whose source turn fell back to the last person turn, household facts whose written owner was cleared, duration_ms.
Never the conversation, the facts or the model's text."""

import logging
import time
from collections import Counter
from collections.abc import Sequence
from datetime import datetime

from .. import logs, services
from ..conversations.model import Conversation
from ..inference.inference import Inference
from ..people.people import People
from . import writer_output, writer_prompt
from .memory import FactWriter
from .model import Fact, Op

log = logging.getLogger("ashley.memory")


class InferenceFactWriter(FactWriter):
    async def decide(self, conversation: Conversation, known: Sequence[Fact], now: datetime) -> tuple[Op, ...]:
        """`FactWriter.decide` by the `memory_write` task. An op naming a target outside `known`, or a person outside
        the conversation's household, is dropped and counted in the log line.

        Raises ValueError when the conversation's household does not exist; PeopleUnavailable; InferenceUnavailable and
        InferenceRefused from the call."""
        started = time.perf_counter()
        household = await services.get(People).household(conversation.household_id)
        if household is None:
            raise ValueError(f"no household {conversation.household_id}")
        prompt = writer_prompt.prompt(conversation, known, household, now)
        written = await services.get(Inference).generate("memory_write", prompt, writer_output.Written,
                                                         conversation_id=conversation.id)
        converted = writer_output.to_ops(written, {f.id for f in known}, {p.id for p in household.people},
                                        conversation.turns)
        kept = Counter(type(op).__name__.lower() for op in converted.ops)
        logs.info(log, "memory.write", conversation=conversation.id, known=len(known), written=len(written.ops),
                  add=kept["add"], update=kept["update"], invalidate=kept["invalidate"], forget=kept["forget"],
                  noop=kept["noop"], dropped_unknown_target=converted.unknown_target,
                  dropped_unknown_person=converted.unknown_person, dropped_empty_text=converted.empty_text,
                  turn_fallback=converted.turn_fallback, owner_cleared=converted.owner_cleared,
                  duration_ms=int((time.perf_counter() - started) * 1000))
        return converted.ops

"""Remembering one line now: a person points at a turn, and the write job's decision (`FactWriter`, against the
current facts most like it, applied through `Memory.apply`) runs over it at once instead of when the conversation goes
idle (`docs/decisions.md`, "People see, correct and forget what she knows of them").

Which turns the writer sees follows the job's watermark, so no line is distilled twice. A turn after the watermark
is written with every unwritten turn before it, exactly as the job would have written the conversation had it gone
idle there, and the watermark moves to it in the same transaction; the job then carries on from the next turn. A turn
the job already wrote is decided again with the turn before it as context, and the watermark stays where it is.
With `answer`, the turn of hers that answered the line is decided with it, and everything above holds for that turn.

Logs `memory.remembered`: conversation and turn ids, whether the watermark moved, turns decided over, the inserted
fact ids, the facts ended and duration_ms. Never text."""

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from .. import logs, services
from ..conversations.model import Conversation, Turn
from ..inference.inference import InferenceRefused, InferenceRejected, InferenceUnavailable
from .memory import AlreadyWritten, FactWriter, Memory
from .model import Fact, Forget, Invalidate, Update
from .write_job import load as load_job_policy

log = logging.getLogger("ashley.memory")


class RememberUnavailable(Exception):
    """The writer's model could not be reached, or the facts it decided against changed under it twice running.
    Transient: the caller may retry. Nothing was applied."""


class RememberRefused(Exception):
    """The writer's model refused to decide over the line, or every route rejected the request (asking again replays
    it). Nothing was applied."""


@dataclass(frozen=True)
class Remembered:
    """`inserted` the facts the decision added or replaced others with, in op order; `ended` how many current facts
    it closed or forgot, `replaced` how many an update replaced with a corrected one."""

    inserted: tuple[int, ...]
    ended: int
    replaced: int = 0


async def remember(conversation: Conversation, turn_id: int, answer: int | None = None, targets: tuple[int, ...] = (),
                   now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> Remembered:
    """Runs the write job's decision over turn `turn_id` of `conversation` and applies it, as the module docstring
    says; `answer` is the turn of hers that answered it. `targets` are ids of facts the line is about: those the
    speaker of the turn may see are among the facts the writer decides against, whatever else is most like it.
    Should the job write the conversation meanwhile, it decides again as for a turn already written, once.
    Raises ValueError when a turn is not in `conversation`; RememberUnavailable; RememberRefused; MemoryUnavailable
    and PeopleUnavailable from the services it calls."""
    ids = {t.id for t in conversation.turns}
    if turn_id not in ids or (answer is not None and answer not in ids):
        raise ValueError(f"turn {turn_id} is not in conversation {conversation.id}")
    started = time.perf_counter()
    try:
        done, moved, turns = await _once(conversation, turn_id, answer, targets, now)
    except (AlreadyWritten, ValueError):
        try:
            done, moved, turns = await _once(conversation, turn_id, answer, targets, now)
        except (AlreadyWritten, ValueError) as e:
            raise RememberUnavailable("the conversation was written meanwhile") from e
    logs.info(log, "memory.remembered", conversation=conversation.id, turn=turn_id, moved=moved, turns=turns,
              inserted=",".join(str(i) for i in done.inserted), ended=done.ended,
              duration_ms=int((time.perf_counter() - started) * 1000))
    return done


async def _once(conversation: Conversation, turn_id: int, answer: int | None, targets: tuple[int, ...],
                now: Callable[[], datetime]) -> tuple[Remembered, bool, int]:
    """One decision and its apply against the watermark as it stands; also whether it moved and the turns decided
    over. Raises AlreadyWritten or apply's ValueError when the job or a correction got there first."""
    memory = services.get(Memory)
    through = await memory.written_through(conversation.id)
    last = answer if answer is not None else turn_id
    moves = last > (through or 0)
    turns = _unwritten_through(conversation.turns, through, last) if moves else _with_context(
        conversation.turns, turn_id, last)
    fresh = replace(conversation, turns=turns)
    known = await _known(fresh, await memory.similar(fresh, load_job_policy().candidates), turn_id, targets)
    try:
        ops = await services.get(FactWriter).decide(fresh, known, now())
    except (InferenceRefused, InferenceRejected) as e:
        raise RememberRefused(f"the writer's model did not take the request ({type(e).__name__})") from e
    except InferenceUnavailable as e:
        raise RememberUnavailable("the writer's model is unavailable") from e
    inserted = await memory.apply(fresh.household_id, fresh.id, ops, now(), last if moves else None, through)
    return Remembered(inserted, sum(isinstance(op, (Invalidate, Forget)) for op in ops),
                      sum(isinstance(op, Update) for op in ops)), moves, len(turns)


async def _known(conversation: Conversation, similar: Sequence[Fact], turn_id: int,
                 targets: tuple[int, ...]) -> tuple[Fact, ...]:
    """`similar` with the `targets` the speaker of `turn_id` may see added, those first."""
    speaker = next(t.speaker_id for t in conversation.turns if t.id == turn_id)
    memory = services.get(Memory)
    named = [h.fact for i in targets if speaker is not None for h in await memory.held(conversation.household_id,
                                                                                       speaker, i)]
    return (*named, *(f for f in similar if f.id not in {n.id for n in named}))


def _unwritten_through(turns: tuple[Turn, ...], through: int | None, last: int) -> tuple[Turn, ...]:
    return tuple(t for t in turns if (through or 0) < t.id <= last)


def _with_context(turns: tuple[Turn, ...], turn_id: int, last: int) -> tuple[Turn, ...]:
    at = next(i for i, t in enumerate(turns) if t.id == turn_id)
    end = next(i for i, t in enumerate(turns) if t.id == last)
    return turns[max(at - 1, 0):end + 1]

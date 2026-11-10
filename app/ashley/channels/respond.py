"""What she says to one message: the turn loop every channel shares. It reaches each system through the locator
(`People`, `Presence`, `Conversations`, `Tools`, `Inference`), so a channel adapter only builds an `Inbound` and
delivers the `Outbound`.

Limits are data (`turns.json` beside this module: per kind, `max_tool_rounds`, the most `ToolCalls` one reply may
make before she must answer, and `max_tool_result_chars`, past which a tool result is cut before the model reads it).

Logs `respond.done` with the conversation id, kind, medium, tool rounds, tool calls, how many steps were asked again
with tools required (`tools_required`), how many of its calls were changes (`changes`), how the turn closed (`closed`,
`tool_loop.Closed`) and the closing reply's `answers`, whether the reply went out later through the outbox (`later`), speaker
`known` or `unknown`, how
many facts were recalled and how many were standing (each `unavailable` when memory was), the offered fact ids the
reply relied on (`used_facts`), the ids offered from each tier in the order offered (`standing_facts`,
`recalled_facts`; empty when none, `unavailable` when memory was), how many ids it named that were not offered
(`used_unrecalled`), how many earlier turns it carried (`recent_turns`, `relevant_turns`) and how many the hearing rule
held back (`turns_filtered`), what tainted the turn (`tainted`, its origin, the first tool whose result carried outside words, or `none`) and how many calls it held for the person's OK (`held`), whether the reply set `Reply.offer` (`offered`; the offer itself is never
delivered), the source it owes (`owed`, or none), whether it set `owed` and was refused (`owed_dropped`), the errand results it was shown (`told`, ids), and duration_ms; `respond.offered` with the conversation id, the names of the tools the turn begins with, how many they are (`tool_count`) and the keys of the sources they come from (`sources`), each `unavailable` when they could not be reached (a log line cuts a long field; the count and the sources it does not); `respond.held` with the conversation id, why it held (`by`, `not_answer`, `aside_budget` or `escalate`) and duration_ms when a reply that is not the answer is returned first; `respond.deadline`
(`tool_loop`) when the turn's deadline forced its answer; `respond.window` and `respond.stood` (`tool_loop`) when a turn took a fresh window, or a closing reply that was not the answer was asked to say where things stand; `respond.escalated` (`tool_loop`, `channels.escalation`) when
the turn went on to the stronger route; `respond.failed` with the reason (`inflight_unavailable`, `claim_lost` and `unstorable` among them) and `later`, and for `unstorable` the error that refused her turn (`cause`) and the check it failed (`check`, a fixed phrase);
`respond.pending` with the conversation and person turn ids, the exception's type and duration_ms when a failed turn's
work may survive; `respond.answered_elsewhere` with the conversation and person turn ids when a message handed in again
already has its work saved or its answer stored; `respond.ended` (`ending.record`) once for each turn that ended after its
first line went out without its answer. Never the text of the message, the reply, any tool result or any fact."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass
from typing import Any

from .. import logs
from ..conversations.conversations import ConversationClosed, ConversationError, ConversationsUnavailable
from ..conversations.inflight import ClaimLost, InFlightUnavailable
from ..conversations.model import Carried, Conversation, NewTurn, Turn
from ..errands.model import Done
from ..inference.inference import InferenceRefused, InferenceUnavailable
from ..inference.model import Message, SystemPrompt, ToolSpec
from ..inference.reply import Reply
from ..people.people import PeopleUnavailable
from ..workshop.model import thread_of
from . import (aloud, answering, bench_after, continued, history, history_runs, inflight, inflight_config, keep, limits, owed, person_turn, prompt,
               recall, settled, speaker, steering, storing, taste, to_phone, tool_loop, unprompted, unsaid)
from .checkpoint import Checkpoint
from .offered import fields as offered_fields
from .landing import Landing
from .live_turn import Showing
from .model import Inbound, Outbound
from .outbox import Pushed
from .render import delivered, render

log = logging.getLogger("ashley.channels")

LIMITS = limits.load()
_running: set[asyncio.Task[None]] = set()

# What makes a reply unavailable, and the reason `respond.failed` gives for it.
_UNAVAILABLE: tuple[tuple[type[Exception], str], ...] = (
    (PeopleUnavailable, "people_unavailable"),
    (ConversationsUnavailable, "conversations_unavailable"),
    (ConversationClosed, "closed_again"),
    (InferenceUnavailable, "inference_unavailable"),
    (InFlightUnavailable, "inflight_unavailable"),
    (ClaimLost, "claim_lost"),
    (inflight.Unstored, "unstorable"),
    (unsaid.Unworded, "unworded"),
)


class RespondError(Exception):
    """Base of what `respond` raises on purpose."""


class RespondUnavailable(RespondError):
    """A system the reply needs could not be reached (People, Conversations or Inference), or no model answered.
    Transient: the channel may tell the person to try again."""


class RespondRefused(RespondError):
    """The model declined to answer. Her refusal is not stored as a turn."""


async def respond(inbound: Inbound) -> Outbound:
    """Her reply to `inbound`, rendered for `inbound.medium`, with both turns stored. `inbound.attachment` is what the person
    pasted or forwarded with the message, stored on their turn and read by her with it (logged `respond.attached`, ids and its length).

    1. The speaker is `inbound.speaker_id`; when that is None and the channel is `shared`, the one person `Presence`
       says is home, if exactly one is; otherwise unknown.
    2. The conversation is `Conversations.for_thread(household, thread, kind, participants, remembered=inbound.remembers)`, the
       speaker its one participant when known. The person turn is added with the speaker, `inbound.source` (a message
       handed in before is the turn stored then, in its own conversation) and who could hear it
       (`history.heard`: private to the speaker on an owner-only channel, else shared). If the conversation closes between the two
       (ConversationClosed), `for_thread` is asked once more and the turn added there.
    3. The system prompt is `persona.system(kind, ...)` with the household's local time and persona overrides (`taste.overrides`). Tools are the catalogue of
       `turn_tools.for_turn(inbound)`, the locator's `Tools` plus what this turn's fields offer; ToolsUnavailable means no tools and `tools_reachable` False, and the reply goes on. What she
       remembers is `Memory.profile` (standing facts) and `Memory.recall` on the message's text for the speaker,
       owner-only when the channel's audience is `owner`, read alongside the catalogue; MemoryUnavailable means she
       is told her memory is out of reach, and the reply goes on.
    4. Messages are the turns `Conversations.carried` gives for the speaker (`history.carried`, budgets per kind in
       `turns.json`): the latest turns across conversations oldest first, each marked with its age, ending with this
       one; a person turn whose speaker is known is prefixed `<name>: `. The older turns matching the message go in the
       system prompt as `said_before`. A turn the reply's hearer may not hear is never read. A carried answer of hers
       ends with the compact form of the code runs its question asked for (`history_runs.carried`, logged `respond.runs`
       with counts); when they cannot be read the reply goes on without them, logged `respond.runs_unavailable`.
    5. `Inference.step(kind, ..., conversation_id=...)` with `Reply` as output, tool choice `auto`. Each `ToolCalls` is run through
       `Tools.call`, one call at a time in the order asked, and sent back as `ToolResults`; a result longer than the
       kind's limit is cut to it. After `max_tool_rounds` rounds, one more step with tool choice `none`. A reply
       under `auto` that says it is not the answer (`Reply.answers` false) is asked again under `auto` with a note to act (`unsaid.acting`).
       A turn that cannot finish on its fast route goes on once on the stronger one (`channels.escalation`).
       When the channel delivers later replies (`inbound.later`), the first such reply, or her latest aside once the
       turn has run past its kind's `hold_after_s` (`tool_loop.answer`), is returned at once instead,
       with `follows` true, and the loop goes on in the background from that step. It is first stored as her turn
       marked `follows` (`NewTurn.follows`), the delivered field heard as in 7, through `Work.say` (under the claim
       on a channel of 10); a conversation refusing it is logged `respond.turn_unrecorded` and it still goes out.
       The answer is stored as in 6 and 7 and, when `inbound.later_by` is `outbox`, queued in the `Outbox` for
       `inbound.thread` in the same transaction (`Outbox.answer`), or logged `respond.failed` with `later` true,
       neither said nor stored. On an unprompted turn (`inbound.unprompted`) nothing holds unless it is `watched`, and the answer is queued
       only when `Initiative` lets it out (`unprompted`), and else stored as her staying quiet.
    6. On a spoken channel, or a turn she was woken for off their phone thread, whose known speaker has a browser subscribed (`to_phone.reachable`; on a woken turn the prompt also says whether they have a page open, `to_phone.looking`), the prompt says `text`
       may go to their phone, and a reply setting `Reply.to_phone` has its `text` queued for that phone
       (`to_phone.copy`, queued in the transaction that stores her turn) as well as `spoken` delivered; otherwise the field
       is ignored. A said-aloud message (`Inbound.said_aloud`) offers `Reply.aloud` too; `spoken` is stored (`Turn.spoken`).
    7. Her turn is added with the delivered field (`spoken` for a spoken medium, `text` for text, and `text` when it
       went to the phone, then private to the speaker), before lexicon, heard as the person turn was. A failure to store it is logged `respond.turn_unrecorded` and the reply is
       still delivered.
    8. A reply setting `Reply.memory` in a remembered conversation has its turn stored `keeping`, and once it is stored
      `keep.now` acts on memory apart from the reply (`keep.py`, through `Work.act`, so on a channel of 10 the act is
      the turn's work's last step): the ids it names that she was not shown are dropped.
   9. Open screens are told through `Live` (`live_turn.Showing`): she is thinking from the start until the turn ends,
       the held answer's included, and each turn stored on an owner's thread.
   11. A turn that moved the speaker's page to a bench is that bench's from then on (`landing.Landing`), its answer
       stored in the bench's talk, its chat turn only continuing there (`continued.said_on_bench`).
   10. On a channel that takes later replies (`inbound.later`), the turn's work is kept in `InFlight` from step 5
       (`inflight.begin`): checkpointed per step and around every change, her turn stored with the work's end, so if
       this runner stops another finishes it (`resume`), its answer queued as a held one's is. A message handed in
       again (`inbound.source`, step 2's turn being the one stored before) whose work is saved or whose answer is stored
       gets no second answer: the reply is pending, logged `respond.answered_elsewhere`. A turn that fails here deletes its work and
       raises as above, only once its work is known to be gone; while it may survive (the database unreachable, or
       another runner holding it) the reply is pending, `follows` true with an empty body, and the runner that
       finishes it delivers the answer as a stored turn. A reply the conversation refuses to store is never sent.

    Raises ValueError for an empty `text` or `thread`, before anything is read or written; RespondUnavailable;
    RespondRefused. When it raises after step 2, the person's turn stays stored: it was said."""
    if not inbound.text.strip() or not inbound.thread.strip():
        raise ValueError("a message has text and a thread")
    started = time.perf_counter()
    showing = Showing(inbound)
    showing.state("thinking")
    held = False
    try:
        out = await _reply(inbound, started, showing)
        held = out.follows
        return out
    except InferenceRefused as e:
        _failed("refused", started)
        raise RespondRefused() from e
    except tuple(kind for kind, _ in _UNAVAILABLE) as e:
        _failed(next(reason for kind, reason in _UNAVAILABLE if isinstance(e, kind)), started, why=_why(e))
        raise RespondUnavailable() from e
    finally:
        if not held:
            showing.state("idle")


async def _reply(inbound: Inbound, started: float, showing: Showing) -> Outbound:
    who = await speaker.who(inbound)
    conversation, said = await person_turn.stored(inbound, who.speaker)
    showing.stored()
    if await steering.running(inbound, conversation.id, said.id):
        showing.state("idle")
        return Outbound(conversation.id, inbound.medium, "", follows=True)
    return await answer_said(inbound, who, conversation, said, started, showing, lambda c: inflight.begin(inbound, c))


async def answer_said(inbound: Inbound, who: speaker.Who, conversation: Conversation, said: Turn, started: float,
                      showing: Showing, begin: Callable[[Checkpoint], Awaitable[inflight.Work]]) -> Outbound:
    """`respond` from step 3 for the person turn `said`, already stored, its work begun by `begin` with the first
    checkpoint (which raises ValueError when the turn is answered elsewhere)."""
    source = Landing(inbound, (conversation.id, said.id), LIMITS)
    catalogue, remembered, phone, page_open, carried, away, overrides = await asyncio.gather(
        tool_loop.offered(source), recall.remembered(inbound, who), to_phone.reachable(inbound, who.speaker),
        to_phone.looking(inbound, who.speaker), history.carried(inbound, who.speaker, conversation.id, said, LIMITS[inbound.kind]),
        owed.untold(inbound, who.speaker), taste.overrides(inbound.household_id))
    logs.info(log, "respond.offered", conversation=conversation.id, **offered_fields(catalogue))
    system = prompt.system(inbound.kind, who, inbound.place, catalogue, remembered.recalled,
                           remembered.standing or (), phone=phone is not None,
                           page_open=page_open if phone is not None else None, aloud=aloud.offered(inbound),
                           said_before=prompt.said_before(carried.relevant, who.household),
                           while_away=owed.lines(away, who.household), overrides=overrides)
    ran = await history_runs.carried(inbound.household_id, carried.recent, said, LIMITS[inbound.kind])
    messages = prompt.messages(carried.recent, said, who.household, ran, inbound.note, carried.places)
    offered = recall.offered_ids(remembered.standing, remembered.recalled)
    try:
        work = await begin(Checkpoint(
            inbound, conversation.id, said.id, None if who.speaker is None else who.speaker.id, system,
            tool_loop.Progress(messages, 0, 0), offered=offered, phone=phone, turn=showing.turn, tainted=inbound.taint))
    except ValueError:
        logs.info(log, "respond.answered_elsewhere", conversation=conversation.id, said=said.id)
        showing.state("idle")
        return Outbound(conversation.id, inbound.medium, "", follows=True)
    source.recording(work)
    turn = _Turn(inbound, conversation.id, said.id, who, remembered, carried, started, showing, phone, offered, work,
                 source, None if catalogue is None else catalogue.unreachable, away)
    try:
        return await _answered(turn, system, messages, catalogue.specs if catalogue is not None else ())
    except Exception as e:
        if await work.drop():
            raise
        logs.warning(log, "respond.pending", conversation=conversation.id, said=said.id, error=type(e).__name__,
                     duration_ms=_ms(started))
        return Outbound(conversation.id, inbound.medium, "", follows=True)


async def _answered(turn: "_Turn", system: Mapping[str, SystemPrompt], messages: tuple[Message, ...],
                    tools: tuple[ToolSpec, ...]) -> Outbound:
    inbound, conversation_id = turn.inbound, turn.conversation_id
    got = await turn.work.guarded(tool_loop.answer(
        inbound.kind, system, messages, tools, LIMITS[inbound.kind], conversation_id, hold=inbound.holds,
        source=turn.landing, started=turn.started, clock=time.perf_counter, steps=turn.work, arrive=turn.arrive,
        medium=inbound.medium, escalation=turn.landing.escalation))
    if isinstance(got, tool_loop.Held):
        logs.info(log, "respond.held", conversation=conversation_id, by=got.by, duration_ms=_ms(turn.started))
        await _said_held(turn, got.reply)
        background(_finish(turn, got, system, tools))
        return Outbound(conversation_id, inbound.medium, await render(got.reply, inbound.medium, inbound.household_id),
                        follows=True)
    got = await answering.stored(turn.work, got, lambda r: _end(turn, r, inbound.unprompted), turn.going(system, tools))
    _done(turn, got, later=False)
    return Outbound(conversation_id, inbound.medium, await render(got.reply, inbound.medium, inbound.household_id),
                    quiet=not unprompted.speaks(got.reply, inbound), receipts=turn.landing.receipts)


@dataclass(frozen=True)
class _Turn:
    """What the end of a turn needs and logs, kept while a held one finishes."""

    inbound: Inbound
    conversation_id: int
    said_id: int
    who: speaker.Who
    remembered: recall.Remembered
    carried: Carried
    started: float
    showing: Showing
    phone: int | None
    offered: frozenset[int]
    work: inflight.Work
    landing: Landing
    unreachable: tuple[str, ...] | None
    away: tuple[Done, ...]

    def going(self, system: Mapping[str, SystemPrompt], tools: tuple[ToolSpec, ...]) -> answering.Going:
        return answering.Going(self.landing, self.conversation_id, system, tools, self.inbound.holds, self.started,
                               self.arrive, self.inbound.medium, self.landing.escalation)

    async def arrive(self, system: Mapping[str, SystemPrompt]) -> tool_loop.Arrived | None:
        return await continued.arrived(self.landing, self.who.speaker, self.said_id, self.showing, self.work, system)


async def _said_held(turn: _Turn, reply: Reply) -> None:
    """The held reply stored as her turn, marked `follows`, before it goes out: the delivered field, heard as her
    answer will be. A conversation that refuses it is logged `respond.turn_unrecorded` and the reply still goes out.
    Raises what `Work.say` raises besides ConversationError and ValueError."""
    inbound = turn.inbound
    said = NewTurn("ashley", delivered(reply, inbound.medium), None, *history.heard(inbound, turn.who.speaker),
                   follows=True, answers=turn.said_id, spoken=aloud.spoken(reply, inbound, turn.conversation_id))
    where, talk = turn.conversation_id, None
    on_bench = await continued.held_on_bench(turn.landing.inbound, turn.who.speaker, turn.said_id, said, turn.showing)
    bench = turn.landing.inbound.lands_on
    if on_bench is not None and bench is not None:
        where, said = on_bench
        talk = thread_of(bench)
    try:
        await turn.work.say(where, said)
    except (ConversationError, ValueError):
        logs.error(log, "respond.turn_unrecorded", exc=True, conversation=where)
        return
    turn.showing.stored(talk)


async def _finish(turn: _Turn, held: tool_loop.Held, system: Mapping[str, SystemPrompt],
                  tools: tuple[ToolSpec, ...]) -> None:
    """The answer a held reply stood in for: queued in the `Outbox` for the thread when the channel takes it from there,
    then stored as her turn. A failure before then is logged `respond.failed` with `later` true and settled
    (`settled.settle`): a refusal was wrapped up in the loop, a model out of reach is told and its work kept, and once
    other work is gone the person's screens are told it failed (`Showing.failed`). She is idle once it is over, unless
    its work may survive, when the runner that finishes it ends her state."""
    inbound = turn.inbound
    now = turn.landing.current(tools, system)
    try:
        answer = await turn.work.guarded(tool_loop.resume(
            held, turn.landing.kind, now.system, now.tools, turn.landing.limits, turn.conversation_id,
            source=turn.landing, started=turn.started, clock=time.perf_counter, steps=turn.work, arrive=turn.arrive,
            medium=inbound.medium, escalation=turn.landing.escalation))
        answer = await answering.stored(turn.work, answer, lambda r: _end(turn, r, True), turn.going(system, tools))
    except Exception as e:
        ended = settled.Ended(inbound, turn.conversation_id, turn.said_id, turn.who.speaker, turn.showing)
        if await settled.settle(turn.work, e, failed_later(e, turn.started), ended, inflight_config.CONFIG.unavailable_retry_s):
            return
    else:
        _done(turn, answer, later=True)
    turn.showing.state("idle")


def failed_later(error: Exception, started: float, resumed: bool = False) -> str | None:
    """Log `respond.failed` with `later` true for `error`, being handled, which ended a turn after its first reply
    went out, or a turn another runner began (`resumed`); its reason, None for an unforeseen error."""
    reason = next((r for kind, r in settled.LATER if isinstance(error, kind)), None)
    if reason is None:
        logs.error(log, "respond.failed", exc=True, reason="error", later=True, resumed=resumed,
                   duration_ms=_ms(started))
    else:
        logs.warning(log, "respond.failed", reason=reason, later=True, resumed=resumed, duration_ms=_ms(started),
                     **_why(error))
    return reason


async def _end(turn: _Turn, reply: Reply, push: bool) -> None:
    """Her turn stored (and, when `push`, queued for the thread with it) and what it asks of memory begun."""
    queued = await storing.pushed(reply, turn.inbound, turn.conversation_id, turn.landing.receipts) if push else ()
    act = keep.act(reply, turn.inbound, turn.offered, turn.conversation_id)
    speaker_id = turn.who.speaker.id if turn.who.speaker is not None else None
    said, queued = storing.stored(reply, turn.inbound, turn.who.speaker, turn.phone, turn.conversation_id,
                                  turn.said_id, queued, turn.landing.receipts)
    said = turn.work.answering(said)
    said = await continued.said_on_bench(turn.landing.inbound, turn.who.speaker, turn.said_id, said,
                                         turn.conversation_id, turn.showing)
    hers = await record(turn.work, turn.conversation_id, said, turn.showing, queued, act)
    kept(turn.work, act, turn.inbound, turn.conversation_id, turn.said_id, hers, speaker_id)
    await owed.settle(reply, turn.unreachable, turn.who.speaker, turn.conversation_id, turn.said_id, turn.away, hers,
                      turn.work.changed)
    bench_after.tidy(turn.landing.inbound, turn.who.speaker)


def _done(turn: _Turn, answer: tool_loop.Answer, later: bool) -> None:
    who, remembered = turn.who, turn.remembered
    used, unrecalled = recall.used(answer.reply, remembered.recalled, remembered.standing)
    logs.info(log, "respond.done", conversation=turn.conversation_id, kind=turn.inbound.kind,
              medium=turn.inbound.medium, tool_rounds=answer.rounds, tool_calls=answer.calls,
              tools_required=answer.required, **answer.closing(), later=later, speaker="unknown" if who.speaker is None else "known",
              recalled="unavailable" if remembered.recalled is None else len(remembered.recalled),
              standing="unavailable" if remembered.standing is None else len(remembered.standing),
              standing_facts=recall.ids(remembered.standing), recalled_facts=recall.ids(remembered.recalled),
              used_facts=",".join(map(str, used)), used_unrecalled=unrecalled, recent_turns=len(turn.carried.recent),
              relevant_turns=len(turn.carried.relevant), turns_filtered=turn.carried.filtered,
              offered=answer.reply.offer is not None, duration_ms=_ms(turn.started), held=turn.landing.held,
              tainted=turn.work.taint or "none", **owed.fields(answer.reply, turn.unreachable, who.speaker, turn.away, turn.work.changed))


def background(work: Coroutine[Any, Any, None]) -> None:
    """Run `work` on its own; the set keeps the task alive until it ends (asyncio holds tasks only weakly)."""
    task = asyncio.create_task(work)
    _running.add(task)
    task.add_done_callback(_running.discard)


async def record(work: inflight.Work, conversation_id: int, said: NewTurn, showing: Showing,
                 queued: tuple[Pushed, ...] = (), act: keep.Act | None = None) -> int | None:
    """Her turn stored through `work` (and `queued` with it, `act` left in its work), and its id; None when the
    conversation refused it, which is logged and the reply still goes out. Raises what `work.store` raises besides
    ConversationError and ValueError."""
    try:
        made = await work.store(conversation_id, said, queued, act)
    except (ConversationError, ValueError):
        logs.error(log, "respond.turn_unrecorded", exc=True, conversation=conversation_id)
        return None
    showing.stored()
    return made.id


def kept(work: inflight.Work, act: keep.Act | None, inbound: Inbound, conversation_id: int, said_id: int,
         hers: int | None, speaker_id: int | None) -> None:
    """`act` (`keep.act` of her reply, read before her turn was stored) done apart from the reply, by `work`
    (`Work.act`)."""
    if act is not None:
        background(work.act(conversation_id, said_id, hers, act, inbound.household_id, speaker_id))


def _failed(reason: str, started: float, later: bool = False, why: Mapping[str, str] = {}) -> None:
    logs.warning(log, "respond.failed", reason=reason, later=later, duration_ms=_ms(started), **why)


def _why(error: Exception) -> dict[str, str]:
    """What refused a reply that could not be stored: the refusing error's class (`cause`) and, for a refused turn,
    which check (`check`); nothing else is added."""
    if not isinstance(error, inflight.Unstored):
        return {}
    return {"cause": error.cause, **({"check": error.check} if error.check else {})}


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)

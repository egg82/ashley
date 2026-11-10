"""A `Tools` for a turn that may have read outside words (`docs/decisions.md`, "A turn that has read outside words asks
before it does anything consequential the person did not ask for"). Reads run. Once the turn is tainted, by its origin or
by a read whose result can carry text written outside the household, a call that is not a read goes by its tier
(`Tools.tier`, else `ToolSpec.tier`): `runs` runs and is recorded, `judged` asks the `ActionJudge`, and an `ask` (or a call
that cannot be recorded) is held in the person's `OUTSIDE` proposal and not run. A tool that takes a person's agreement
(`ToolSpec.agrees`) is refused. A person's later, untainted turn agrees with `carry_out`, which runs the stored calls
through the source with the arguments that were stored.

The first taint is recorded through `Tainting` (a `channels.steps.Steps`) before the tainting result is returned. Logs
`outside.tainted`, `outside.tier`, `outside.judged`, `outside.held`, `outside.refused`, `outside.unrecorded`, `outside.receipts` and `outside.carried_out` with ids, tool names, tiers, decisions,
reason enums and counts, never arguments, summaries, explanations or results. The judge's one-sentence explanation is
stored with a held call and in the record of a change that ran, and is shown to the person beside her reply
(`receipts`) and to her in what she is handed (`HeldCall.explanation`, `DoneAction.explanation`), never logged."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from .. import logs, services
from ..receipts import AgreedCall, Receipt, Receipts
from ..inference.model import Tier, ToolCall, ToolResult, ToolSpec
from ..senses.outside_record import DoneAction, OutsideRecord, OutsideRecordUnavailable
from ..senses.proposal_payloads import OUTSIDE, HeldCall, HeldCalls
from ..senses.proposals import Proposal, ProposalRefused, Proposals, ProposalsUnavailable, refusal
from . import outside_config, outside_judging, outside_summary, tainted
from .action_judge import Verdict
from .outside_config import OutsideConfig
from .outside_judging import Judged, Words
from .tools import Catalogue, Tools, ToolsUnavailable

log = logging.getLogger("ashley.tools")
CARRY_OUT = "carry_out"


class Tainting(Protocol):
    async def tainted(self, tool: str) -> bool:
        """Record that the result of the call to `tool` is the first to carry outside words; true when it was the
        first. Raises when the turn cannot be saved, so the result is not used."""
        ...


class _Untracked:
    """Where a turn records nothing: no taint is saved, and a verdict is kept in memory alone."""

    def __init__(self) -> None:
        self._verdicts: dict[str, Verdict] = {}

    async def tainted(self, tool: str) -> bool:
        return False

    async def judged(self, call_id: str, verdict: Verdict) -> None:
        self._verdicts[call_id] = verdict

    def judgement(self, call_id: str) -> Verdict | None:
        return self._verdicts.get(call_id)


@dataclass(frozen=True)
class _Cleared:
    """A call of a tainted turn that may run: its `tier`, and the judge's `verdict` when it was `judged`."""

    tier: Tier
    verdict: Verdict | None = None


@dataclass(frozen=True)
class _Ran:
    held: HeldCall
    spec: ToolSpec | None
    got: ToolResult | None


@dataclass(frozen=True)
class Standing:
    """Who the turn answers, from the channel's fields: the `speaker_id` of `household_id`, whether the reply reaches them
    alone (`private`, `channels.audience.owner_alone`), and whether the turn may agree to held calls (`agreeing`: a
    person's own message whose origin is not tainted)."""

    household_id: int
    speaker_id: int
    private: bool
    agreeing: bool


class Outside(Tools):
    def __init__(self, source: Tools, standing: Standing | None, turn: tuple[int, int] | None,
                 steps: Tainting | None = None, tainted: str | None = None,
                 config: OutsideConfig | None = None, words: Words | None = None) -> None:
        """`turn` is the conversation and the person turn being answered; `tainted` what tainted the turn already (its
        origin, or the tool a resumed checkpoint names); `words` reads what the person said, which the action judge
        judges a call by (`channels.judge_words`): a turn with none holds every judged call. Without a `standing` and a
        `turn` nothing is held: a change after the taint is refused, as in a shared room."""
        self._source, self._standing, self._turn = source, standing, turn
        self._steps: Tainting = steps or _Untracked()
        self._saved: Judged = _Untracked()
        self._tainted = tainted
        self._words = words
        self._config = config or outside_config.load()
        self._specs: dict[str, ToolSpec] | None = None
        self._held = 0
        self._agree: int | None = None
        self._unrecorded: list[Receipt] = []

    @property
    def tainted(self) -> str | None:
        """The origin or the first tool that tainted the turn, None while it has read none."""
        return self._tainted

    @property
    def held(self) -> int:
        """How many calls this turn has held so far, as last counted."""
        return self._held

    @property
    def agree(self) -> int | None:
        """The id of the proposal the receipts last built show, None when they showed none."""
        return self._agree

    def recording(self, steps: Tainting) -> None:
        """Where the first taint is saved."""
        self._steps = steps

    def judging(self, saved: Judged) -> None:
        """Where the verdicts on judged calls are saved, and read back by a runner that resumes the turn."""
        self._saved = saved

    async def catalogue(self) -> Catalogue:
        """The source's, and `carry_out` when this turn may agree to what is held. Raises ToolsUnavailable."""
        got = await self._listed()
        if self._tainted is not None or not await self._can_carry():
            return got
        return replace(got, specs=(*got.specs, ToolSpec(
            CARRY_OUT, self._config.carry_out_description, {"type": "object", "properties": {}}, outside=False,
            agrees=True)))

    async def call(self, call: ToolCall) -> ToolResult:
        """The source's answer; or, in a tainted turn, a refusal for a tool that agrees and a result saying a change is
        held; `carry_out` is this class's own. A change that ran on its own is recorded (`OutsideRecord`)."""
        if call.name == CARRY_OUT:
            return await self._carry(call)
        spec = await self._spec(call.name)
        sorted_: _Cleared | None = None
        if self._tainted is not None:
            if spec is not None and spec.agrees:
                return self._refused(call, "agreeing_tainted", self._config.agreeing_tainted)
            if spec is None or not spec.reads:
                cleared = await self._sorted(call, spec)
                if isinstance(cleared, ToolResult):
                    return cleared
                sorted_ = cleared
        with tainted.bound(self._tainted, self._turn):
            got = await self._source.call(call)
        if sorted_ is not None and not got.is_error:
            await self._done(call, spec, sorted_)
            got = self._explained(got, sorted_)
        return await self._recorded(call.name, got, got.outside if got.outside is not None else spec is None or spec.outside)

    async def receipts(self) -> Receipts | None:
        """What code shows beside her reply (`conversations.model.Receipts`): the changes the action judge let run this
        turn, from the record and from memory for one that could not be recorded, then each call held in the turn's
        proposal in full. A `runs`-tier change is recorded but not shown. None when the turn is not tainted or did and
        held nothing. Counts `held` and keeps the proposal's id (`agree`)."""
        if self._tainted is None:
            return None
        found = await self._held_proposal()
        calls = () if found is None else found.payload.calls
        self._held = len(calls)
        self._agree = None if found is None or not calls else found.id
        held = tuple([Receipt(h.label or await self._headline(h.tool), h.summary, h.explanation or None) for h in calls])
        done = (*await self._done_receipts(), *self._unrecorded)
        logs.info(log, "outside.receipts", conversation=self._conversation(), turn=self._turn_id(), done=len(done),
                  held=len(held))
        if not done and not held:
            return None
        return Receipts(done, held, self._agree)

    async def _done_receipts(self) -> tuple[Receipt, ...]:
        if self._turn is None:
            return ()
        private = self._standing is not None and self._standing.private
        try:
            rows = await services.get(OutsideRecord).of_turn(*self._turn)
        except OutsideRecordUnavailable:
            logs.warning(log, "outside.unavailable", conversation=self._turn[0], turn=self._turn[1], where="receipts")
            return ()
        return tuple(Receipt(a.label or self._config.unlabelled, a.summary if private else None, a.explanation)
                     for a in rows if a.tier == "judged")

    async def _headline(self, tool: str) -> str:
        spec = await self._spec(tool)
        return self._config.unlabelled if spec is None or spec.label is None else spec.label

    async def _listed(self) -> Catalogue:
        got = await self._source.catalogue()
        self._specs = {s.name: s for s in got.specs}
        return got

    async def _spec(self, name: str) -> ToolSpec | None:
        """`name`'s spec as the source lists it now (asked again for a name not seen, as a page move changes the
        tools); None when it lists no such tool or cannot be listed."""
        if self._specs is None or name not in self._specs:
            try:
                await self._listed()
            except ToolsUnavailable:
                self._specs = self._specs or {}
        return (self._specs or {}).get(name)

    async def _recorded(self, tool: str, got: ToolResult, taints: bool) -> ToolResult:
        if taints and self._tainted is None:
            await self._steps.tainted(tool)
            self._tainted = tool
            logs.info(log, "outside.tainted", conversation=self._conversation(), turn=self._turn_id(), by=tool)
        return got

    def _conversation(self) -> int | None:
        return None if self._turn is None else self._turn[0]

    def _turn_id(self) -> int | None:
        return None if self._turn is None else self._turn[1]

    def _refused(self, call: ToolCall, reason: str, text: str) -> ToolResult:
        logs.info(log, "outside.refused", conversation=self._conversation(), turn=self._turn_id(), tool=call.name,
                  reason=reason)
        return ToolResult(call.id, text, True)

    async def _held_proposal(self) -> Proposal[HeldCalls] | None:
        """This turn's pending proposal; None when it holds none, the pending one is another turn's or the store is out of
        reach."""
        if self._standing is None or self._turn is None:
            return None
        try:
            found = await services.get(Proposals).pending(self._standing.speaker_id, self._turn[0], OUTSIDE)
        except ProposalsUnavailable:
            logs.warning(log, "outside.unavailable", conversation=self._turn[0], turn=self._turn[1], where="pending")
            return None
        return found if found is not None and found.turn_id == self._turn[1] else None

    async def _held_calls(self) -> tuple[HeldCall, ...]:
        found = await self._held_proposal()
        return () if found is None else found.payload.calls

    async def _sorted(self, call: ToolCall, spec: ToolSpec | None) -> _Cleared | ToolResult:
        """A change in a tainted turn by its tier: cleared to run, or the result of holding or refusing it. A change that
        cannot be recorded (no known speaker or turn) is not cleared."""
        tier: Tier = await self._source.tier(call) or (spec.tier if spec is not None else "judged")
        logs.info(log, "outside.tier", conversation=self._conversation(), turn=self._turn_id(), tool=call.name, tier=tier)
        if self._standing is None or self._turn is None:
            return await self._hold(call)
        if tier == "runs":
            return _Cleared(tier)
        verdict = await outside_judging.verdict_on(call, spec, tier, self._source, self._words, self._saved, self._config,
                                                   self._turn)
        if verdict.decision == "run":
            return _Cleared(tier, verdict)
        return await self._hold(call, verdict.explanation)

    def _explained(self, got: ToolResult, cleared: _Cleared) -> ToolResult:
        """`got`, and when the judge ran it, the line saying why, which she reads with the result."""
        if cleared.verdict is None:
            return got
        return replace(got, content=f"{got.content}\n{self._config.why_ran.format(why=cleared.verdict.explanation)}")

    async def _done(self, call: ToolCall, spec: ToolSpec | None, cleared: _Cleared) -> None:
        """Record the change that ran. One that cannot be stored is still shown beside her reply, from memory."""
        st, turn = self._standing, self._turn
        if st is None or turn is None:
            return
        named = self._config.summary_arguments.get(call.name, ())
        label = self._config.unlabelled if spec is None or spec.label is None else spec.label
        shown = outside_summary.done_summary(label, call.arguments, named) if st.private else label
        verdict = cleared.verdict
        action = DoneAction(st.household_id, st.speaker_id, *turn, call.name, shown, cleared.tier,
                            None if verdict is None else verdict.reason, None if verdict is None else verdict.explanation,
                            datetime.now(UTC), label)
        try:
            await services.get(OutsideRecord).done(action)
        except OutsideRecordUnavailable:
            if cleared.tier == "judged":
                self._unrecorded.append(Receipt(label, shown if st.private else None,
                                                None if verdict is None else verdict.explanation))
            logs.warning(log, "outside.unrecorded", conversation=turn[0], turn=turn[1], tool=call.name)

    async def _can_carry(self) -> bool:
        st = self._standing
        if st is None or self._turn is None or not (st.agreeing and st.private):
            return False
        try:
            found = await services.get(Proposals).pending(st.speaker_id, self._turn[0], OUTSIDE)
        except ProposalsUnavailable:
            return False
        return found is not None and refusal(found, self._turn[1], datetime.now(UTC), self._config.proposal_ttl_s) is None

    async def _hold(self, call: ToolCall, why: str = "") -> ToolResult:
        st, turn = self._standing, self._turn
        if st is None or turn is None or not st.private:
            return self._refused(call, "needs_private", self._config.needs_private)
        arguments: Mapping[str, Any] = outside_summary.plain(call.arguments)
        if outside_summary.arguments_chars(arguments) > self._config.max_argument_chars:
            return self._refused(call, "too_long", self._config.too_long)
        try:
            held = await self._held_calls()
            said = self._config.held if not why else f"{self._config.held} {self._config.why_held.format(why=why)}"
            if any(h.tool == call.name and h.arguments == arguments for h in held):
                return ToolResult(call.id, said, False)
            if len(held) >= self._config.max_calls:
                return self._refused(call, "too_many", self._config.too_many)
            label = await self._headline(call.name)
            calls = (*held, HeldCall(call.name, arguments, outside_summary.summary(label, arguments), why,
                                           label))
            proposal = Proposal(st.household_id, st.speaker_id, turn[0], turn[1], datetime.now(UTC), HeldCalls(calls))
            stored = await services.get(Proposals).propose(proposal, self._config.proposal_ttl_s)
        except ProposalsUnavailable:
            logs.warning(log, "outside.unavailable", conversation=turn[0], turn=turn[1], where="propose")
            return ToolResult(call.id, self._config.unavailable, True)
        self._held = len(calls)
        logs.info(log, "outside.held", conversation=turn[0], turn=turn[1], tool=call.name, calls=len(calls),
                  proposal=stored)
        return ToolResult(call.id, said, False)

    async def _carry(self, call: ToolCall) -> ToolResult:
        st, turn = self._standing, self._turn
        if st is None or turn is None:
            return ToolResult(call.id, f"no tool named {CARRY_OUT}", True)
        if self._tainted is not None:
            return self._refused(call, "agreeing_tainted", self._config.agreeing_tainted)
        if not (st.agreeing and st.private):
            return ToolResult(call.id, f"no tool named {CARRY_OUT}", True)
        try:
            taken = await services.get(Proposals).take(st.speaker_id, turn[0], OUTSIDE, turn[1],
                                                       self._config.proposal_ttl_s)
        except ProposalRefused:
            return ToolResult(call.id, self._config.nothing_to_carry_out, True)
        except ProposalsUnavailable:
            return ToolResult(call.id, self._config.unavailable, True)
        got = await self._run_held(call, taken.payload.calls)
        return await self._recorded(call.name, got, got.outside is True)

    async def agreed(self, call_id: str, proposal_id: int) -> tuple[AgreedCall, ...]:
        """The held calls of proposal `proposal_id` taken (consumed) and run in order, as `carry_out` runs them, and what
        became of each: its summary and whether it ran, failed or was not offered. Never what a call returned, which
        may be outside words. Raises ValueError unless this turn is a person's own, untainted and private;
        ProposalRefused when the proposal is gone, expired, another person's or from this turn or later;
        ProposalsUnavailable."""
        st, turn = self._standing, self._turn
        if st is None or turn is None or self._tainted is not None or not (st.agreeing and st.private):
            raise ValueError("this turn cannot agree")
        taken = await services.get(Proposals).take_by_id(proposal_id, OUTSIDE, st.speaker_id, turn[1],
                                                         self._config.proposal_ttl_s)
        ran = await self._run_each(call_id, taken.payload.calls)
        return tuple(AgreedCall(r.held.summary, "not_run" if r.got is None else "failed" if r.got.is_error else "ran")
                     for r in ran)

    async def _run_held(self, call: ToolCall, held: tuple[HeldCall, ...]) -> ToolResult:
        """Each held call, in order, through the source with its stored name and arguments under new call ids; a tool the
        source does not offer now is reported as not run."""
        lines: list[str] = []
        tainting = False
        for i, r in enumerate(await self._run_each(call.id, held), 1):
            if r.got is None or r.spec is None:
                lines.append(f"{i}. {r.held.summary}: {self._config.not_run}")
                continue
            tainting = tainting or (r.spec.outside if r.got.outside is None else r.got.outside)
            lines.append(f"{i}. {r.held.summary}: {'error: ' if r.got.is_error else ''}{r.got.content}")
        return ToolResult(call.id, "\n".join(lines), outside=tainting)

    async def _run_each(self, call_id: str, held: tuple[HeldCall, ...]) -> list[_Ran]:
        offered = await self._offered()
        done: list[_Ran] = []
        for i, h in enumerate(held, 1):
            spec = offered.get(h.tool)
            got = None if spec is None else await self._source.call(ToolCall(f"{call_id}.{i}", h.tool, h.arguments))
            done.append(_Ran(h, spec, got))
        ran = sum(1 for r in done if r.got is not None)
        logs.info(log, "outside.carried_out", conversation=self._conversation(), turn=self._turn_id(), calls=len(held),
                  ran=ran, not_offered=len(held) - ran)
        return done

    async def _offered(self) -> dict[str, ToolSpec]:
        try:
            await self._listed()
        except ToolsUnavailable:
            return {}
        return self._specs or {}

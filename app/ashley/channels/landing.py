"""A turn that takes the speaker's page to a bench becomes that bench's turn from the next model step on
(`docs/decisions.md`, "Her reply follows the page"): she is offered the bench's tools, told how to work there, and
her reply is said in the bench's talk. `Landing` is the turn's tool source: it answers as `turn_tools.for_turn` of the
turn as it is now, and rebuilds that when `open_bench` and `move_page` (through `tools.arrival.Arrival`) have moved
the page. What the turn is is `Inbound.moved_to`, saved with its checkpoint the moment the call that moved the page
returns, so a runner that resumes it is already there (and guides the saved system prompt again on its first step).
The turn's numbered search results (`tools.results.Results`) live here, bound while a call runs, so what one look-up
found a bench tool of the same turn can name; a runner that resumes the turn starts with none."""

from collections.abc import Mapping, Sequence
from dataclasses import replace

from ..conversations.model import AgreedCall, Fact, Kind, Receipts, Shown
from ..inference.model import Entry, SystemPrompt, Tier, ToolCall, ToolResult, ToolResults, ToolSpec
from ..inference.reply import Reply
from ..tools.action_judge import Vetting
from ..tools.arrival import Arrival
from ..tools import outside_config
from ..tools.outside import Outside
from ..tools.results import Results, bound
from ..tools.tools import Catalogue, Tools, ToolsUnavailable
from . import bench_facts, cut, escalation, judge_words, on_demand, standing, turn_tools
from .limits import Limits
from .model import Inbound
from .tool_loop import NO_STEPS, Arrived, Steps


class _Current(Tools):
    """The tools the turn has as its page is now, which `Outside` stands in front of."""

    def __init__(self, landing: "Landing") -> None:
        self._landing = landing

    async def catalogue(self) -> Catalogue:
        return await self._landing.inner.catalogue()

    async def call(self, call: ToolCall) -> ToolResult:
        with bound(self._landing.results):
            return await self._landing.inner.call(call)

    async def tier(self, call: ToolCall) -> Tier | None:
        return await self._landing.inner.tier(call)

    async def vetted(self, call: ToolCall, words: Sequence[str]) -> Vetting | None:
        return await self._landing.inner.vetted(call, words)

    async def shown(self, call: ToolCall) -> str | None:
        return await self._landing.inner.shown(call)


class Landing(Tools):
    def __init__(self, inbound: Inbound, said: tuple[int, int], limits: Mapping[Kind, Limits],
                 tainted: str | None = None) -> None:
        """`tainted` is what already tainted the turn when a runner resumes it (`Checkpoint.tainted`); a new turn starts
        with its origin's (`Inbound.taint`)."""
        self._limits = limits
        self._inbound = inbound
        self._said = said
        self._arrival = Arrival(inbound.moved_to)
        self.results = Results()
        self.inner = self._built()
        config = outside_config.load()
        words = judge_words.reader(inbound, said[0], config.words_turns, config.words_chars)
        self._outside = Outside(standing.trusting(inbound, _Current(self)), standing.of(inbound), said,
                                tainted=tainted or inbound.taint, config=config, words=words)
        self._receipts: Receipts | None = None
        self._shown: tuple[Shown, ...] = ()
        self._facts: tuple[Fact, ...] | None = None
        self._arrived: Arrived | None = None
        self._base: Mapping[str, SystemPrompt] | None = None
        self._loaded: frozenset[str] = frozenset()
        self._guided: int | None = None
        self._steps: Steps = NO_STEPS

    @property
    def kind(self) -> Kind:
        """The turn's conversation kind, which picks its model and limits: a bench talk's once its page is on a bench."""
        return "brainstorm" if self._inbound.moved_to is not None else self._inbound.kind

    @property
    def limits(self) -> Limits:
        return self._limits[self.kind]

    @property
    def escalation(self) -> escalation.Escalation | None:
        """How the turn escalates (`channels.escalation`); None when its kind does not, on a channel that takes no reply
        said after the response, and once its page is on a bench."""
        if not self._inbound.later or self._inbound.moved_to is not None:
            return None
        return escalation.of(self._inbound.kind, self._limits)

    def current(self, tools: tuple[ToolSpec, ...], system: Mapping[str, SystemPrompt]) -> Arrived:
        """What the turn is offered now: what the last move gave it, else `tools` and `system`, the turn's own."""
        return self._arrived or Arrived(tools, system, self.limits, self.kind)

    @property
    def inbound(self) -> Inbound:
        """The message as the turn is now: `moved_to` the bench its page is on."""
        return self._inbound

    async def catalogue(self) -> Catalogue:
        return await self._outside.catalogue()

    def recording(self, steps: Steps) -> None:
        """Where the turn is saved as its page moves and as it is first tainted."""
        self._steps = steps
        self._outside.recording(steps)
        self._outside.judging(steps)

    @property
    def held(self) -> int:
        """How many calls the turn has held for the person's OK (`tools.outside`)."""
        return self._outside.held

    @property
    def receipts(self) -> Receipts | None:
        """What code shows beside her reply, once `closing` built it (`Outside.receipts`); None before, and when the turn
        did and held nothing."""
        return self._receipts

    @property
    def brought_up(self) -> tuple[Shown, ...]:
        """What the turn's calls brought up beside her words (`ToolResult.shown`), each once, in the order first brought
        up; a resumed turn's include those of the calls made before it was resumed (`resuming`)."""
        return self._shown

    def resuming(self, entries: tuple[Entry, ...], done: Mapping[str, ToolResult]) -> None:
        """What the calls a resumed turn already made brought up: those in its saved `entries` and the round in flight
        (`done`)."""
        before = [r for e in entries if isinstance(e, ToolResults) for r in e.results]
        self._shown = tuple(dict.fromkeys(x for r in (*before, *done.values()) for x in r.shown))

    @property
    def agree(self) -> int | None:
        """The held proposal `receipts` shows, None when it shows none."""
        return None if self._receipts is None else self._receipts.proposal_id

    async def agreed(self, call_id: str, proposal_id: int) -> tuple[AgreedCall, ...]:
        """`Outside.agreed` for this turn: the held calls of `proposal_id` run through the turn's tools, no model asked."""
        return await self._outside.agreed(call_id, proposal_id)

    async def closing(self, reply: Reply) -> Reply:
        """`reply` as it is stored: her words untouched, and said (`says` `reply`) whatever she set when the turn held
        calls, since a held change nobody sees is lost. What code shows beside it is built here (`receipts`): on a
        bench, with a reply that is said, the choice rows the person has not been shown too (`bench_facts.shown`),
        recorded shown the first time this is asked, so a turn closed again after a steer shows the same ones."""
        self._receipts = await self._outside.receipts()
        if self._receipts is not None and self._receipts.held and reply.says == "none":
            reply = reply.model_copy(update={"says": "reply"})
        if self._facts is None and reply.says != "none":
            self._facts = await bench_facts.shown(self._inbound, self._said[1])
        if self._facts:
            self._receipts = (Receipts(facts=self._facts) if self._receipts is None
                              else replace(self._receipts, facts=self._facts))
        return reply

    async def call(self, call: ToolCall) -> ToolResult:
        """The call, run by the turn's tools as they are; if it moved the page, the turn is saved as the bench's before
        its result is returned, so no kill between the move and the next step resumes it in chat."""
        got = await self._outside.call(call)
        self._shown = tuple(dict.fromkeys((*self._shown, *got.shown)))
        bench = self._arrival.bench
        if bench != self._inbound.moved_to:
            self._inbound = replace(self._inbound, moved_to=bench)
            if bench is not None:
                self.inner = self._built()
            await self._steps.arrived(self._inbound)
        return got

    def _built(self) -> Tools:
        """What `turn_tools.for_turn` offers the turn as it is now, with the loader tool (`on_demand`) when the turn has a
        core (`on_demand.core_for`)."""
        tools = turn_tools.for_turn(self._inbound, self._said, self._arrival, self.results)
        core = on_demand.core_for(self._inbound)
        return tools if core is None else on_demand.Loading(tools, core)

    async def arrived(self, system: Mapping[str, SystemPrompt], entries: tuple[Entry, ...]) -> Arrived | None:
        """Asked before each step: when the page is on a bench this has not yet guided, the tools that bench offers and
        `system` with how to work there; before it is, the groups of tools `entries` show she asked for when they are
        not yet offered, with their instructions added to `system` (`on_demand`); None otherwise. A runner that resumes
        a moved turn starts unguided, so the saved `system` is guided on its first step, and one that resumes a turn
        that loaded groups offers them on its first."""
        bench = self._arrival.bench
        if bench is None:
            return await self._loading(system, entries)
        if bench == self._guided:
            return None
        self._guided = bench
        try:
            specs = (await self._outside.catalogue()).specs
        except ToolsUnavailable:
            specs = ()
        guidance = await self._guidance()
        moved = {k: replace(v, moment=f"{v.moment}\n\n{guidance}") for k, v in system.items()}
        self._arrived = Arrived(specs, moved, self.limits, self.kind)
        return self._arrived

    async def _loading(self, system: Mapping[str, SystemPrompt], entries: tuple[Entry, ...]) -> Arrived | None:
        groups = on_demand.loaded(entries)
        self._base = self._base or system
        if groups == self._loaded:
            return None
        try:
            full = await self._outside.catalogue()
        except ToolsUnavailable:
            return None
        self._loaded = groups
        guidance = "\n\n".join(text for key, text in full.guidance.items() if key in groups)
        base = {k: replace(v, moment=f"{v.moment}\n\n{guidance}") for k, v in self._base.items()} if guidance else self._base
        self._arrived = Arrived(cut.thinned(on_demand.thinned(full, groups)).specs, base, page=False)
        return self._arrived

    async def _guidance(self) -> str:
        found = turn_tools.sources(self._inbound, self._arrival)
        got = [await found[k].catalogue() for k in ("bench", "tidy", "automations", "skills") if k in found]
        return "\n\n".join(text for text in (*(c.instructions for c in got), *(c.now for c in got)) if text)

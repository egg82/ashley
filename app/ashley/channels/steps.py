"""Where a turn records its progress as its tool loop goes (`ashley.channels.tool_loop`); the base records nothing, and
`ashley.channels.inflight.Saved` keeps a turn's work in `InFlight`."""

from ..inference.model import Entry, Message, ToolCall, ToolCalls, ToolResult
from ..tools.action_judge import Verdict
from .escalation import Trigger
from .model import Inbound


class Steps:
    """Where a turn records its progress as its loop goes (`ashley.channels.inflight`); this one records nothing.
    `asked`: the model asked for `asked` in round `rounds` after `entries`, `calls` counting them. `starting`: a change
    is about to run; it must not run when this raises. `ran`: a call's result, as cut, is in. `tainted`: the result of
    the call to `tool` is the first to carry outside words (`channels.taint`); recorded before the result goes back to
    the loop, and true when it was the first. `judged`: the action judge's `verdict` on the call `call_id` is recorded
    before the call runs, and `judgement` gives it back to a runner that resumes the turn, so a call is judged once. `taint` is what tainted the turn (its origin or that tool), if anything. `changed`: whether a change has begun on
    the turn (`starting` was called)."""

    async def asked(self, entries: tuple[Entry, ...], asked: ToolCalls, rounds: int, calls: int) -> None:
        return None

    async def starting(self, call: ToolCall) -> None:
        return None

    async def ran(self, result: ToolResult) -> None:
        return None

    async def tainted(self, tool: str) -> bool:
        return False

    async def judged(self, call_id: str, verdict: Verdict) -> None:
        return None

    def judgement(self, call_id: str) -> Verdict | None:
        return None

    @property
    def taint(self) -> str | None:
        return None

    @property
    def changed(self) -> bool:
        return False

    @property
    def escalated(self) -> Trigger | None:
        """What escalated the turn, when it already has: it goes on, from its entries, on the stronger route."""
        return None

    async def escalate(self, trigger: Trigger) -> None:
        """The turn escalated for `trigger`, before its holding line goes out: recorded, so a runner that resumes the
        turn is on the stronger route and does not escalate again."""
        return None

    async def arrived(self, inbound: Inbound) -> None:
        """The turn's page moved (`landing.Landing`), as soon as the call that moved it returned: the turn is now
        `inbound`."""
        return None

    async def carried(self, talk: int, ask: int) -> None:
        """The turn's ask was carried into the bench talk `talk` as the turn `ask` (`continued.carried`): the turn is
        that talk's running turn from now on."""
        return None

    @property
    def windows(self) -> int:
        """How many fresh windows the turn has taken."""
        return 0

    async def windowed(self) -> None:
        """The turn took a fresh window (`Limits.windows`): its window count is one more and its work in the window
        none, recorded before its next step."""
        return None

    @property
    def cut_off(self) -> int:
        """How many steps of the turn were asked again to act small after a reply was cut off at the token limit."""
        return 0

    async def cut(self) -> None:
        """A step is about to be asked again to act small (`unsaid.TOO_BIG`): recorded first, so a runner that resumes
        the turn does not ask it again."""
        return None

    async def worked(self, seconds: float) -> None:
        """`seconds` of work have passed in the turn's current window, recorded so a runner that resumes the turn counts
        its deadline from them."""
        return None

    async def steer(self, entries: tuple[Entry, ...], rounds: int, calls: int) -> tuple[Message, ...]:
        """Between rounds, with the turn at `entries` (ending with her draft when she had answered): what the person
        said to the turn since it last asked, to be added to `entries` as they stand, recorded with them so a runner
        that resumes the turn has both."""
        return ()


NO_STEPS = Steps()

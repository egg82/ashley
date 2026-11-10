"""The tool loop records the first result that can carry outside words through `Steps.tainted`, before the result goes
back: by the result's own `outside` when it says, else its spec's, and a name the turn was not offered taints. The
origin taint stays, and a taint never clears. Recording changes nothing the loop does."""

from collections.abc import Mapping

import pytest
from ashley import logs
from ashley.channels.inflight import Unsaved
from ashley.channels.limits import Limits
from ashley.channels.steps import Steps
from ashley.channels.tool_loop import answer
from ashley.inference.model import Message, SystemPrompt, ToolCall, ToolCalls, ToolResult, ToolSpec
from ashley.tools.tools import Catalogue, Tools
from contract.turns_support import World, world as world
from contract.inference_support import settle

OBJ: Mapping[str, object] = {"type": "object", "properties": {}}
PAGE = ToolSpec("page", "reads a page", OBJ, reads=True, outside=True)
STATE = ToolSpec("state", "reads the house", OBJ, reads=True, outside=False)
SWITCH = ToolSpec("switch", "changes", OBJ, outside=False)
UNMARKED = ToolSpec("unmarked", "reads, unclassified", OBJ, reads=True)
LIMITS = Limits(max_tool_rounds=4, max_tool_result_chars=1000, recent_turns=1, relevant_turns=0)


class Source(Tools):
    def __init__(self, narrowed: dict[str, bool | None]) -> None:
        self.narrowed = narrowed

    async def catalogue(self) -> Catalogue:
        return Catalogue((PAGE, STATE, SWITCH, UNMARKED), "")

    async def call(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.id, "{}", outside=self.narrowed.get(call.name))


class Recording(Unsaved):
    def __init__(self, taint: str | None = None) -> None:
        super().__init__(taint)
        self.tools_asked: list[str] = []
        self.order: list[str] = []

    async def tainted(self, tool: str) -> bool:
        self.tools_asked.append(tool)
        self.order.append("tainted")
        return await super().tainted(tool)

    async def ran(self, result: ToolResult) -> None:
        self.order.append("ran")


def run(world: World, *rounds: tuple[str, ...], steps: Steps, narrowed: dict[str, bool | None] | None = None,
        tools: tuple[ToolSpec, ...] = (PAGE, STATE, SWITCH, UNMARKED)) -> None:
    world.inference.script = [ToolCalls(tuple(ToolCall(f"r{i}c{j}", n, {"j": j}) for j, n in enumerate(names)))
                              for i, names in enumerate(rounds)]
    settle(answer("chat", {"default": SystemPrompt("x")}, (Message("person", "hi"),), tools, LIMITS, 7,
                  source=Source(narrowed or {}), steps=steps))


def test_a_read_whose_spec_is_outside_taints_the_turn_by_that_tool(world: World) -> None:
    steps = Recording()
    run(world, ("state", "page", "switch"), steps=steps)
    assert steps.taint == "page" and steps.tools_asked == ["page"]


def test_a_turn_that_read_only_the_households_own_state_stays_untainted(world: World) -> None:
    steps = Recording()
    run(world, ("state", "switch"), steps=steps)
    assert steps.taint is None and steps.tools_asked == []


def test_a_spec_that_does_not_say_taints() -> None:
    assert ToolSpec("x", "d", OBJ).outside is True


def test_a_result_that_says_false_narrows_an_outside_spec(world: World) -> None:
    steps = Recording()
    run(world, ("page",), steps=steps, narrowed={"page": False})
    assert steps.taint is None and steps.tools_asked == []


def test_a_result_that_says_true_widens_a_spec_that_says_false(world: World) -> None:
    steps = Recording()
    run(world, ("state",), steps=steps, narrowed={"state": True})
    assert steps.taint == "state"


def test_a_tool_the_turn_was_not_offered_taints(world: World) -> None:
    steps = Recording()
    run(world, ("state",), steps=steps, tools=(PAGE,))
    assert steps.taint == "state"


def test_an_unclassified_spec_taints(world: World) -> None:
    steps = Recording()
    run(world, ("unmarked",), steps=steps)
    assert steps.taint == "unmarked"


def test_the_origin_stays_and_a_later_read_does_not_replace_it(world: World) -> None:
    steps = Recording(taint="stranger")
    run(world, ("page",), steps=steps)
    assert steps.taint == "stranger" and steps.tools_asked == ["page"]


def test_the_first_tainting_tool_is_kept_across_rounds(world: World) -> None:
    steps = Recording()
    run(world, ("state",), ("page",), ("unmarked",), steps=steps, narrowed={"state": True})
    assert steps.taint == "state"


def test_a_read_repeated_in_a_reply_is_not_a_new_taint(world: World) -> None:
    steps = Recording()
    world.inference.script = [ToolCalls((ToolCall("a", "page", {"j": 0}), ToolCall("b", "page", {"j": 0})))]
    settle(answer("chat", {"default": SystemPrompt("x")}, (Message("person", "hi"),), (PAGE,), LIMITS, 7,
                  source=Source({}), steps=steps))
    assert steps.tools_asked == ["page"]


def test_the_taint_is_logged_with_ids_and_the_tool_and_no_result(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    run(world, ("page",), steps=Recording())
    out = capsys.readouterr().out
    assert "outside.tainted" in out and "by=page" in out and "conversation=7" in out


def test_the_taint_is_recorded_before_its_result_is_taken_in(world: World) -> None:
    steps = Recording()
    run(world, ("page",), steps=steps)
    assert steps.order == ["tainted", "ran"]

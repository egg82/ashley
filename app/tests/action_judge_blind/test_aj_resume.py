"""A verdict is saved through the turn's `Steps` before the call runs (design 3.5): a pod killed between judging and
running neither runs twice nor flips the decision when another runner resumes the turn."""

from collections.abc import Generator
from dataclasses import replace

import pytest
from action_judge_blind_support import Crashing, Judged, Keeping, free_text_source, prompt_call, run_judged, says
from ashley import services
from ashley.channels.checkpoint import loads
from ashley.channels.inflight import Saved
from ashley.conversations.inflight import Claim, InFlight
from ashley.inference.model import ToolCall
from ashley.tools.outside import Outside
from inflight_blind.ifb_checkpoint_support import checkpoint


@pytest.fixture
def kept() -> Generator[Keeping]:
    store = Keeping()
    services.register(InFlight, store)
    yield store
    services.unregister(InFlight)


def outside_over(j: Judged, src: Crashing, saved: Saved) -> Outside:
    return j.w.wrap(src, turn=j.say("please tell Claude to go on"), steps=saved, tainted=saved.taint)


def test_a_resumed_turn_reuses_the_saved_verdict_and_does_not_ask_the_judge_again(db_url: str, kept: Keeping) -> None:
    async def body(j: Judged) -> None:
        start = replace(checkpoint(), tainted="look_up")
        claim = Claim(start.said_id, start.conversation_id, "h")
        first = Saved(claim, start)
        crashing = Crashing(free_text_source().specs, "claude_prompt")
        with pytest.raises(RuntimeError):
            await outside_over(j, crashing, first).call(prompt_call())
        assert j.calls == 1 and crashing.crashed and kept.saved, "the judge answered, then the pod died"
        resumed = Saved(claim, loads(kept.saved[-1]))
        src = Crashing(free_text_source().specs, "none")
        got = await outside_over(j, src, resumed).call(prompt_call())
        assert j.calls == 1, "the checkpointed verdict is not asked for again"
        assert [c.name for c in src.reached("claude_prompt")] == ["claude_prompt"] and not got.is_error
        control = await outside_over(j, src, resumed).call(ToolCall("another", "claude_prompt", {"session": "s-9", "prompt": "y"}))
        assert j.calls == 2 and "held" in control.content, "control: a different call is judged, and the script now says ask"

    run_judged(db_url, body, [says("run"), says("ask", "not_asked")])


def test_a_resumed_turn_keeps_a_saved_ask_even_when_the_judge_would_now_say_run(db_url: str, kept: Keeping) -> None:
    async def body(j: Judged) -> None:
        start = replace(checkpoint(), tainted="look_up")
        claim = Claim(start.said_id, start.conversation_id, "h")
        src = free_text_source()
        await outside_over(j, Crashing(src.specs, "none"), Saved(claim, start)).call(prompt_call())
        assert j.calls == 1 and kept.saved
        resumed = Saved(claim, loads(kept.saved[-1]))
        again = free_text_source()
        await outside_over(j, Crashing(again.specs, "none"), resumed).call(prompt_call())
        assert j.calls == 1 and again.reached("claude_prompt") == []

    run_judged(db_url, body, [says("ask", "not_asked"), says("run")])

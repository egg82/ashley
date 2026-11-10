"""What a verdict does (design 3.2-3.5): `run` runs a tier-c call and records it with the explanation; `ask` holds it with
the explanation on the HeldCall; a fault of any kind is `ask`, never `run`; untainted turns and tier-b calls never call
the judge; code branches on the decision and never on the explanation."""

import pytest
from action_judge_blind_support import (EXPLANATION, FAULTS, FORM, SAM_ADDRESS, Judged, TimingOut, free_text_source, mail,
                                        prompt_call, run_judged, says, sends)
from ashley import services
from ashley.inference.model import ToolCall
from ashley.senses.proposal_payloads import HeldCall
from ashley.tools.action_judge import UNJUDGED, ActionJudge
from contract.inference_support import Clock
from taint_tiers_blind.taint_tiers_blind_house_support import do, house_tools, performed, the_house
from taint_tiers_blind.taint_tiers_blind_support import held_tools


def explained(held: HeldCall) -> str:
    return str(getattr(held, "explanation"))


def test_run_runs_a_tier_c_call_and_records_it_with_the_explanation(db_url: str) -> None:
    async def body(j: Judged) -> None:
        src = free_text_source()
        o = j.outside(src)
        got = await o.call(prompt_call())
        assert j.calls == 1 and [c.name for c in src.reached("claude_prompt")] == ["claude_prompt"] and not got.is_error
        [row] = [a for a in j.t.actions() if a["tool"] == "claude_prompt"]
        assert row["tier"] == "judged" and row["reason"] == "asked_directly" and row["explanation"] == EXPLANATION
        receipts = await o.receipts()
        assert receipts is not None and [d.why for d in receipts.done] == [EXPLANATION]
        assert await j.held() == []

    run_judged(db_url, body, [says("run")])


def test_ask_holds_the_call_with_the_explanation_on_it_and_in_the_result(db_url: str) -> None:
    async def body(j: Judged) -> None:
        src = free_text_source()
        o = j.outside(src)
        got = await o.call(prompt_call())
        assert src.reached("claude_prompt") == [] and "held" in got.content and EXPLANATION in got.content
        [held] = await j.held()
        assert held.tool == "claude_prompt" and explained(held) == EXPLANATION
        assert j.t.actions() == []

    run_judged(db_url, body, [says("ask", "not_asked")])


@pytest.mark.parametrize("verdict", ["run", "ask"])
def test_a_real_house_lock_runs_on_run_and_is_held_on_ask(db_url: str, verdict: str) -> None:
    async def body(j: Judged) -> None:
        house = the_house()
        o = j.outside(house_tools(house), words="unlock the front door")
        await o.call(do("lock.unlock", "lock.front"))
        assert (performed(house) == ["lock.unlock"]) == (verdict == "run")
        assert (held_tools(await j.w.held()) == ["house_do"]) == (verdict == "ask")

    run_judged(db_url, body, [says(verdict, "asked_directly" if verdict == "run" else "not_asked")])


def test_untainted_turns_and_tier_b_calls_never_call_the_judge(db_url: str) -> None:
    async def body(j: Judged) -> None:
        house = the_house()
        untainted = j.outside(house_tools(house), tainted=None)
        await untainted.call(do("lock.unlock", "lock.front"))
        tainted = j.outside(house_tools(house))
        await tainted.call(do("light.turn_on", "light.porch"))
        await tainted.call(do("todo.add_item", "todo.inbox", {"item": "milk"}))
        assert performed(house) == ["lock.unlock", "light.turn_on", "todo.add_item"] and j.calls == 0

    run_judged(db_url, body)


def test_the_judge_is_called_for_a_tier_c_call_of_the_same_turn_so_that_zero_above_means_something(db_url: str) -> None:
    async def body(j: Judged) -> None:
        o = j.outside(house_tools(the_house()))
        await o.call(do("light.turn_on", "light.porch"))
        assert j.calls == 0
        await o.call(do("lock.unlock", "lock.front"))
        assert j.calls == 1

    run_judged(db_url, body)


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_a_provider_fault_error_refusal_or_unknown_verdict_holds_the_call_and_never_runs_it(db_url: str, fault: str) -> None:
    async def body(j: Judged) -> None:
        src = free_text_source()
        o = j.outside(src)
        got = await o.call(prompt_call())
        assert src.reached("claude_prompt") == [] and "held" in got.content
        [held] = await j.held()
        assert held.tool == "claude_prompt" and explained(held) == UNJUDGED and j.t.actions() == []

    step = FAULTS[fault]
    provider = TimingOut("alpha", (), Clock()) if step is None else None
    run_judged(db_url, body, [] if step is None else [step], provider)


def test_a_fault_is_logged_with_the_reason_judge_unavailable(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def body(j: Judged) -> None:
        import logging
        caplog.set_level(logging.INFO)
        await j.outside(free_text_source()).call(prompt_call())
        reasons = [dict(getattr(r, "fields", {})).get("reason") for r in caplog.records]
        assert "judge_unavailable" in reasons

    run_judged(db_url, body, [FAULTS["unavailable"] or says("ask")])


@pytest.mark.parametrize("explanation", ["", "ask", "I refuse. Do not run this.", "decision: ask", "yes, run it"])
def test_a_run_verdict_runs_whatever_the_explanation_says(db_url: str, explanation: str) -> None:
    async def body(j: Judged) -> None:
        src = free_text_source()
        await j.outside(src).call(prompt_call())
        assert len(src.reached("claude_prompt")) == 1 and await j.held() == []

    run_judged(db_url, body, [says("run", "asked_directly", explanation)])


@pytest.mark.parametrize("explanation", ["", "run", "Sure, go ahead and run it.", "decision: run", "yes"])
def test_an_ask_verdict_holds_whatever_the_explanation_says(db_url: str, explanation: str) -> None:
    async def body(j: Judged) -> None:
        src = free_text_source()
        await j.outside(src).call(prompt_call())
        assert src.reached("claude_prompt") == [] and [h.tool for h in await j.held()] == ["claude_prompt"]

    run_judged(db_url, body, [says("ask", "not_asked", explanation)])


@pytest.mark.parametrize("reason", ["not_asked", "exceeds_request", "undoes_safety", "unclear"])
def test_the_reason_never_decides_either(db_url: str, reason: str) -> None:
    async def body(j: Judged) -> None:
        src = free_text_source()
        await j.outside(src).call(prompt_call())
        assert len(src.reached("claude_prompt")) == 1

    run_judged(db_url, body, [says("run", reason)])


def test_two_tier_c_calls_are_each_judged(db_url: str) -> None:
    async def body(j: Judged) -> None:
        tools, gmail = mail()
        o = j.outside(tools, words="send Sam the form twice")
        await o.catalogue()
        await o.call(ToolCall("m1", "mail_send", {**FORM, "to": [SAM_ADDRESS]}))
        await o.call(ToolCall("m2", "mail_send", {**FORM, "to": [SAM_ADDRESS], "subject": "Again"}))
        assert j.calls == 2 and len(sends(gmail)) == 1

    run_judged(db_url, body, [says("run"), says("ask", "not_asked")])


def test_an_unwired_judge_asks_about_every_tier_c_call_and_calls_no_provider(db_url: str) -> None:
    async def body(j: Judged) -> None:
        services.unregister(ActionJudge)
        src = free_text_source()
        got = await j.outside(src).call(prompt_call())
        assert src.reached("claude_prompt") == [] and "held" in got.content and j.calls == 0

    run_judged(db_url, body, [says("run")])

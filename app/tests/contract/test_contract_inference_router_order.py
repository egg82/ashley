"""Route order under random failure patterns: for any list of routes (each on its own provider, some unwired) and any
script of outcomes, three consecutive calls (the third after the cooldown) call exactly the providers the contract
says, in order, and end the way it says."""

from dataclasses import dataclass

import pytest
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.inference.reply import Reply
from hypothesis import given, settings
from hypothesis import strategies as st
from inference_support import (COOLDOWN_S, Clock, FakeLedger, FakeProvider, Step, fail, ok, prompt, refuse, route, router,
                               settle, table)

OUTCOMES = ("ok", "refused", "unavailable", "invalid_output", "error")
ROUNDS = 3


def step(outcome: str, who: str) -> Step:
    if outcome == "ok":
        return ok(who)
    if outcome == "refused":
        return refuse()
    if outcome == "unavailable":
        return fail("unavailable")
    if outcome == "invalid_output":
        return fail("invalid_output")
    return fail("error")


@dataclass(frozen=True)
class Plan:
    wired: tuple[bool, ...]
    scripts: tuple[tuple[str, ...], ...]   # per route, its outcome on each call made to it


plans = st.integers(1, 6).flatmap(lambda n: st.builds(
    Plan,
    st.tuples(*[st.booleans()] * n),
    st.tuples(*[st.tuples(*[st.sampled_from(OUTCOMES)] * ROUNDS)] * n)))


def expected(plan: Plan) -> list[tuple[list[tuple[str, str]], str]]:
    """Per round: the (provider, outcome) calls made in order, and how the round ended (`ok:<provider>`, `refused`
    or `unavailable`)."""
    resting: set[int] = set()
    made = [0] * len(plan.wired)
    rounds: list[tuple[list[tuple[str, str]], str]] = []
    for r in range(ROUNDS):
        if r == ROUNDS - 1:
            resting.clear()   # the cooldown has passed before the last round
        calls: list[tuple[str, str]] = []
        ended = "unavailable"
        for i, wired in enumerate(plan.wired):
            if not wired or i in resting:
                continue
            outcome = plan.scripts[i][made[i]]
            made[i] += 1
            calls.append((f"p{i}", outcome))
            if outcome == "ok":
                ended = f"ok:p{i}"
                break
            if outcome == "refused":
                ended = "refused"
                break
            if outcome == "unavailable":
                resting.add(i)
        rounds.append((calls, ended))
    return rounds


@given(plans)
@settings(max_examples=80, deadline=None)
def test_calls_made_and_how_each_call_ends_follow_the_route_order_the_skips_and_the_rests(plan: Plan) -> None:
    clock, ledger = Clock(), FakeLedger()
    providers = [FakeProvider(f"p{i}", [step(o, f"p{i}") for o in plan.scripts[i]], clock)
                 for i in range(len(plan.wired)) if plan.wired[i]]
    inference = router(table([route(f"p{i}") for i in range(len(plan.wired))]), providers, ledger, clock)

    async def one_round() -> str:
        try:
            return f"ok:{(await inference.generate('chat', prompt('hi'), Reply)).text}"
        except InferenceRefused:
            return "refused"
        except InferenceUnavailable:
            return "unavailable"

    seen = 0
    for r, (want_calls, want_end) in enumerate(expected(plan)):
        if r == ROUNDS - 1:
            clock.advance(COOLDOWN_S + 1)
        assert settle(one_round()) == want_end
        got = [(row.provider, row.outcome) for row in ledger.rows[seen:]]
        assert got == want_calls
        seen = len(ledger.rows)


def test_the_property_can_see_a_wrong_order() -> None:
    """Control: the reference itself distinguishes the orders it is meant to pin down."""
    a = Plan((True, True), (("unavailable", "ok", "ok"), ("ok", "ok", "ok")))
    b = Plan((True, True), (("ok", "ok", "ok"), ("ok", "ok", "ok")))
    assert expected(a) != expected(b)
    assert expected(a)[0][0] == [("p0", "unavailable"), ("p1", "ok")]
    assert expected(a)[1][0] == [("p1", "ok")], "p0 is resting in the second round"
    assert expected(a)[2][0] == [("p0", "ok")], "and tried again in the third"


@pytest.mark.parametrize("outcome", OUTCOMES)
def test_each_outcome_ends_a_single_route_call_as_the_contract_says(outcome: str) -> None:
    provider = FakeProvider("p0", [step(outcome, "p0")])
    inference = router(table([route("p0")]), [provider])
    if outcome == "ok":
        assert settle(inference.generate("chat", prompt("hi"), Reply)).text == "p0"
    else:
        with pytest.raises(InferenceRefused if outcome == "refused" else InferenceUnavailable):
            settle(inference.generate("chat", prompt("hi"), Reply))

"""How a call's outcome reaches the watch: the real router writing the real Postgres ledger, read back by `shares`
under the shipped failing set."""

import pytest
from ashley.inference import watch
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.inference.outcomes import Share, shares
from ashley.inference.reply import Reply
from provider_watch_blind_support import FAILURES, Scripted, LAMP, go, prompt, rig, routed, config

KINDS = ["ok", "refused", *FAILURES]


@pytest.mark.parametrize("kind", KINDS)
def test_a_call_is_recorded_under_its_provider_with_the_outcome_it_had(db_url: str, kind: str) -> None:
    async def scenario() -> dict[str, Share | None]:
        async with rig(db_url) as r:
            inference = routed(r.ledger, [Scripted("alpha", [kind])])
            try:
                await inference.generate("chat", prompt(), Reply)
            except (InferenceRefused, InferenceUnavailable):
                pass
            found: dict[str, Share | None] = {}
            for name in KINDS:
                [one] = await shares(r.db, 600, ["chat"], [name])
                found[name] = one
            return found

    found = go(scenario())
    for name, one in found.items():
        assert one == Share("chat", "alpha", 1, 1 if name == kind else 0)


def test_a_fall_through_hides_the_failing_provider_from_the_caller_but_not_from_the_ledger(db_url: str) -> None:
    async def scenario() -> tuple[int, list[Share], list[Share]]:
        async with rig(db_url) as r:
            first, second = Scripted("alpha", ["error"]), Scripted("beta", ["ok"])
            inference = routed(r.ledger, [first, second])
            for _ in range(5):
                await inference.generate("chat", prompt(), Reply)
            seen = await shares(r.db, 600, ["chat"], list(FAILURES))
            return second.calls, seen, await watch.evaluate(config())

    answered, seen, alerted = go(scenario())
    assert answered == 5
    assert seen == [Share("chat", "alpha", 5, 5), Share("chat", "beta", 5, 0)]
    assert alerted == [Share("chat", "alpha", 5, 5)]


def test_a_call_is_recorded_under_the_task_it_served(db_url: str) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url) as r:
            inference = routed(r.ledger, [Scripted("alpha", ["ok"])])
            await inference.generate("command", prompt(), Reply)
            return await shares(r.db, 600, ["chat", "command"], list(FAILURES))

    assert go(scenario()) == [Share("command", "alpha", 1, 0)]


def test_tool_calls_the_prompt_offered_are_an_ok_call(db_url: str) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url) as r:
            inference = routed(r.ledger, [Scripted("alpha", ["tools"])])
            await inference.step("chat", prompt((LAMP,)), Reply)
            return await shares(r.db, 600, ["chat"], ["ok"])

    assert go(scenario()) == [Share("chat", "alpha", 1, 1)]


def test_tool_calls_the_prompt_did_not_offer_are_a_failed_call_the_next_route_answers(db_url: str) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url) as r:
            inference = routed(r.ledger, [Scripted("alpha", ["stray_tools"]), Scripted("beta", ["ok"])])
            await inference.step("chat", prompt((LAMP,)), Reply)
            return await shares(r.db, 600, ["chat"], ["invalid_output"])

    assert go(scenario()) == [Share("chat", "alpha", 1, 1), Share("chat", "beta", 1, 0)]

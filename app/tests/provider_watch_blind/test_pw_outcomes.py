"""`outcomes.shares`: what the ledger says about how each provider answered lately, on the real Postgres ledger."""

from ashley.inference.model import Task
from ashley.inference.outcomes import Share, shares
from provider_watch_blind_support import go, rig

FAILING = ["error", "unavailable", "invalid_output"]


def test_an_empty_ledger_has_no_pairs(db_url: str) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url) as r:
            return await shares(r.db, 600, ["chat"], FAILING)

    assert go(scenario()) == []


def test_calls_and_failed_are_counted_per_task_and_provider(db_url: str) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url) as r:
            await r.add("chat", "gemini", "error", 3)
            await r.add("chat", "gemini", "ok", 2)
            await r.add("chat", "anthropic", "ok", 4)
            await r.add("command", "gemini", "unavailable", 1)
            return await shares(r.db, 600, ["chat", "command"], FAILING)

    assert go(scenario()) == [Share("chat", "anthropic", 4, 0), Share("chat", "gemini", 5, 3),
                              Share("command", "gemini", 1, 1)]


def test_pairs_are_ordered_by_task_then_provider(db_url: str) -> None:
    pairs: list[tuple[Task, str]] = [("command", "alpha"), ("chat", "zeta"), ("command", "zeta"), ("chat", "alpha")]

    async def scenario() -> list[tuple[str, str]]:
        async with rig(db_url) as r:
            for task, provider in pairs:
                await r.add(task, provider, "ok")
            return [(s.task, s.provider) for s in await shares(r.db, 600, ["chat", "command"], FAILING)]

    assert go(scenario()) == [("chat", "alpha"), ("chat", "zeta"), ("command", "alpha"), ("command", "zeta")]


def test_only_the_asked_tasks_are_counted(db_url: str) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url) as r:
            await r.add("chat", "gemini", "error", 2)
            await r.add("command", "gemini", "error", 9)
            await r.add("brainstorm", "gemini", "error", 9)
            return await shares(r.db, 600, ["chat"], FAILING)

    assert go(scenario()) == [Share("chat", "gemini", 2, 2)]


def test_only_the_outcomes_in_the_failing_set_are_failed(db_url: str) -> None:
    async def scenario() -> tuple[list[Share], list[Share], list[Share], list[Share]]:
        async with rig(db_url) as r:
            for outcome in ("ok", "refused", "error", "unavailable", "invalid_output"):
                await r.add("chat", "gemini", outcome)
            return (await shares(r.db, 600, ["chat"], FAILING), await shares(r.db, 600, ["chat"], ["refused"]),
                    await shares(r.db, 600, ["chat"], ["error"]), await shares(r.db, 600, ["chat"], []))

    shipped, refused, error, none = go(scenario())
    assert shipped == [Share("chat", "gemini", 5, 3)]
    assert refused == [Share("chat", "gemini", 5, 1)]
    assert error == [Share("chat", "gemini", 5, 1)]
    assert none == [Share("chat", "gemini", 5, 0)]


def test_a_call_older_than_the_window_is_not_counted(db_url: str) -> None:
    async def scenario() -> tuple[list[Share], list[Share]]:
        async with rig(db_url) as r:
            await r.add("chat", "gemini", "error", 2, age_s=500)
            await r.add("chat", "gemini", "error", 3, age_s=700)
            return await shares(r.db, 600, ["chat"], FAILING), await shares(r.db, 3600, ["chat"], FAILING)

    short, long = go(scenario())
    assert short == [Share("chat", "gemini", 2, 2)]
    assert long == [Share("chat", "gemini", 5, 5)]


def test_a_pair_whose_calls_are_all_older_than_the_window_is_absent(db_url: str) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url) as r:
            await r.add("chat", "gemini", "error", 2, age_s=900)
            await r.add("chat", "anthropic", "ok", 1)
            return await shares(r.db, 600, ["chat"], FAILING)

    assert go(scenario()) == [Share("chat", "anthropic", 1, 0)]


def test_the_window_is_in_seconds_and_may_be_short(db_url: str) -> None:
    async def scenario() -> list[Share]:
        async with rig(db_url) as r:
            await r.add("chat", "gemini", "error", 1, age_s=30)
            await r.add("chat", "gemini", "ok", 1, age_s=120)
            return await shares(r.db, 60, ["chat"], FAILING)

    assert go(scenario()) == [Share("chat", "gemini", 1, 1)]

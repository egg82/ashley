"""`runner.sweep()` housekeeping and who the turn is with: pruning, a log with nothing of the wake in it, a person of
another household, a rule on another bench, workshop and people out of reach, and the turn's thread, privacy and memory."""


from typing import Any

import pytest
from ashley import logs
from contract.conversations_support import run
from contract.test_inflight_resume import World
from wb_runner_support import (DONE, stack, sweep)

HERS = DONE.text


def test_settled_wakes_older_than_the_keeping_are_pruned_by_the_sweep_and_unsettled_stay(world: World) -> None:
    import psycopg

    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            done = await s.hand_in("done")
            await sweep()
            waiting = await s.hand_in("later", event="never_answered")
            with psycopg.connect(world.url, autocommit=True) as conn:
                conn.execute("UPDATE wakes SET settled_at = settled_at - interval '30 days', "
                             "received_at = received_at - interval '30 days' WHERE id = %s", (done,))
                conn.execute("UPDATE wakes SET received_at = received_at - interval '30 days' WHERE id = %s", (waiting,))
            await sweep()
            assert not s.exists(done)
            assert s.exists(waiting)

    run(go())


def test_nothing_of_a_wake_reaches_a_log_line(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "debug"})
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            await s.hand_in("PLANTED-EVID-zq", who="person.alana", what="plantedwhat")
            await s.hand_in("e2", who="person.plantedwho", what="plantedwhat")
            await sweep()

    run(go())
    out = capsys.readouterr().out
    assert "event=wakes.settled" in out
    for planted in ("PLANTED-EVID-zq", "plantedwho", "plantedwhat", "PLANTED-BRIEF-zq", "person.alana", "Welcome home"):
        assert planted not in out


def test_a_person_of_another_household_is_no_person(world: World) -> None:
    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            id_ = await s.hand_in(who="person.kim")
            await sweep()
            assert s.outcome(id_) == "no_person"

    run(go())
    assert world.first.inference.prompts == []


def test_a_rule_on_another_persons_bench_of_the_household_answers(world: World) -> None:
    from ashley.workshop.model import Owner
    from contract.conversations_support import person

    world.first.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            sam = person(world.url, world.who.household_id, "Sam")
            bench = await s.workshop.open(Owner(world.who.household_id, sam), "sam's")
            from ashley.workshop.commands import Add
            from ashley.workshop.model import By, Text
            await s.workshop.apply(Owner(world.who.household_id, sam), bench.id, Add(
                By(sam), "wake", Text("rule", '{"event": "arrived", "brief": "Hi.", "tools": []}'), "small"))
            id_ = await s.hand_in()
            await sweep()
            assert s.outcome(id_) == "turn"

    run(go())


def test_a_workshop_out_of_reach_leaves_the_wake_due_for_the_next_sweep(world: World) -> None:
    from ashley import services
    from ashley.workshop.workshop import Workshop

    world.first.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            id_ = await s.hand_in()
            real = services.get(Workshop)
            services.unregister(Workshop)
            assert await sweep() == 1
            assert s.outcome(id_) is None
            services.register(Workshop, real)
            await s.rule()
            await sweep()
            assert s.outcome(id_) == "turn"

    run(go())


def test_people_out_of_reach_leave_the_wake_due_for_the_next_sweep(world: World) -> None:
    from ashley import services
    from ashley.people.people import People

    world.first.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            id_ = await s.hand_in()
            people: Any = services.get(People)
            people.down = True
            await sweep()
            assert s.outcome(id_) is None
            people.down = False
            await sweep()
            assert s.outcome(id_) == "turn"

    run(go())


def test_the_wake_is_the_households_turn_with_its_id_as_source_and_her_turn_follows_it(world: World) -> None:
    from contract.conversations_support import scalar

    world.first.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            id_ = await s.hand_in()
            await sweep()
            assert s.turns_of(id_) == 1
            assert scalar(world.url, "SELECT count(*) FROM turns WHERE author = 'household' AND household_id = %s AND source = %s",
                  (world.who.household_id, f"wake:{id_}")) == 1

    run(go())


def test_the_wake_is_the_households_turn_in_the_persons_own_private_conversation_and_not_remembered(world: World) -> None:
    from contract.conversations_support import scalar

    world.first.inference.script = [DONE]

    async def go() -> None:
        async with stack(world) as s:
            await s.rule()
            await s.hand_in()
            await sweep()

    run(go())
    url = world.url
    assert scalar(url, "SELECT count(*) FROM turns WHERE author = 'household' AND speaker_id IS NULL") == 1
    assert scalar(url, "SELECT count(*) FROM turns WHERE author = 'person'") == 0
    assert scalar(url, "SELECT count(*) FROM turns WHERE visibility <> 'private'") == 0
    assert scalar(url, "SELECT count(*) FROM conversations WHERE remembered") == 0
    assert scalar(url, "SELECT count(*) FROM conversation_participants WHERE person_id = %s", (world.who.id,)) == 1

"""The shadow job (`workshop.shadow_job`) over a real database, a fake HA and a HeldStates that keeps the recorders it
is given: it holds the event types for the households with a run and lets go of the rest; each `ashley_shadow` event
is a would-have-fired of the run it names and each `automation_triggered` of the automation a run mirrors a did-fire,
told twice counting once; a run keeps its newest firings only, and firings past the retention limit go; a run whose
end has come is undone as its person and the shadow leaves the house; an end that cannot be carried out still ends
the run; a house out of reach is counted and the rest of the pass still runs."""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from ashley import services
from ashley.home_assistant.held_states import EntityState, HeldStates, HouseEvent, Recorder
from ashley.home_assistant.house import HouseUnavailable
from ashley.workshop import shadow, shadow_job
from ashley.workshop.commands import Undo
from ashley.workshop.install_piece import carry_out
from ashley.workshop.model import Owner
from ashley.workshop.shadows import Shadows
from ashley.workshop.workshop import Workshop
from automations_support import FakeHouse
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run
from install_support import world
from test_shadow_install import shadowed

SETTINGS = shadow.Settings(duration_s=3600, keep_s=1000, max_events=3, shown=2, tick_s=1)
NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


@dataclass
class FakeHeld(HeldStates):
    """Keeps what each household was asked to hold; `down` households cannot be reached."""

    held: dict[int, Mapping[str, Recorder]] = field(default_factory=dict[int, Mapping[str, Recorder]])
    down: set[int] = field(default_factory=set[int])

    async def hold(self, changed: Any) -> None:
        return None

    async def states(self, household_id: int, entity_ids: Any) -> Mapping[str, EntityState | None] | None:
        return None

    async def events(self, household_id: int, types: Mapping[str, Recorder]) -> None:
        if household_id in self.down:
            raise HouseUnavailable("down")
        self.held[household_id] = dict(types)

    async def told(self, household_id: int, event: HouseEvent) -> None:
        await self.held[household_id][event.type](event)


def owner(url: str) -> Owner:
    home = household(url)
    return Owner(home, person(url, home))


def event(kind: str, data: dict[str, object], context: str, at: datetime = NOW) -> HouseEvent:
    return HouseEvent(kind, data, at, context)


async def running(alana: Owner, turn_off: str | None = None) -> int:
    bench, applied = await shadowed(alana, turn_off)
    await carry_out(alana, bench, applied)
    return bench


async def tick(at: datetime = NOW, watching: set[int] | None = None) -> Counter[str]:
    return await shadow_job.tick(at, set() if watching is None else watching)


def test_it_holds_the_event_types_for_a_household_with_a_run_and_lets_go_when_it_has_none(db_url: str) -> None:
    alana = owner(db_url)
    fake = FakeHeld()

    async def scenario() -> None:
        async with world(db_url, FakeHouse(), SETTINGS):
            services.register(HeldStates, fake)
            try:
                watching: set[int] = set()
                await tick(NOW, watching)
                assert fake.held == {}
                bench = await running(alana)
                counts = await tick(NOW, watching)
                assert set(fake.held[alana.household_id]) == {"ashley_shadow", "automation_triggered"}
                assert counts["households"] == 1 and watching == {alana.household_id}
                await services.get(Shadows).end(bench, 3, NOW)
                await tick(NOW, watching)
                assert fake.held[alana.household_id] == {} and watching == set()
            finally:
                services.unregister(HeldStates)
    run(scenario())


def test_a_shadow_event_is_a_would_and_the_mirrored_automations_trigger_a_did_each_counted_once(db_url: str) -> None:
    alana = owner(db_url)
    fake = FakeHeld()

    async def scenario() -> None:
        async with world(db_url, FakeHouse(), SETTINGS):
            services.register(HeldStates, fake)
            try:
                bench = await running(alana, turn_off="automation.old")
                await tick()
                async def told(e: HouseEvent) -> None:
                    await fake.told(alana.household_id, e)

                await told(event("ashley_shadow", {"bench": bench, "piece": 1, "version": 1}, "w1"))
                await told(event("ashley_shadow", {"bench": bench, "piece": 1, "version": 1}, "w1"))
                await told(event("ashley_shadow", {"bench": bench, "piece": 1, "version": 1}, "w2", NOW + timedelta(minutes=1)))
                await told(event("ashley_shadow", {"bench": bench + 99, "piece": 1, "version": 1}, "w3"))
                await told(event("ashley_shadow", {"bench": "x", "piece": None}, "w4"))
                await told(event("automation_triggered", {"entity_id": "automation.old"}, "d1"))
                await told(event("automation_triggered", {"entity_id": "automation.old"}, "d1"))
                await told(event("automation_triggered", {"entity_id": "automation.other"}, "d2"))
                seen = (await services.get(Shadows).of_bench(alana.household_id, bench))[1]
                assert (seen.would, seen.did) == (2, 1)
                assert [(f.kind, f.at) for f in seen.firings] == [("would", NOW + timedelta(minutes=1)), ("did", NOW)]
            finally:
                services.unregister(HeldStates)
    run(scenario())


def test_a_run_keeps_its_newest_firings_only(db_url: str) -> None:
    alana = owner(db_url)
    fake = FakeHeld()

    async def scenario() -> None:
        async with world(db_url, FakeHouse(), SETTINGS):
            services.register(HeldStates, fake)
            try:
                bench = await running(alana)
                await tick()
                for n in range(5):
                    await fake.told(alana.household_id, event("ashley_shadow", {"bench": bench, "piece": 1, "version": 1},
                                                             f"c{n}", NOW + timedelta(minutes=n)))
                seen = (await services.get(Shadows).of_bench(alana.household_id, bench))[1]
                assert seen.would == SETTINGS.max_events
                assert [f.at for f in seen.firings] == [NOW + timedelta(minutes=4), NOW + timedelta(minutes=3)]
            finally:
                services.unregister(HeldStates)
    run(scenario())


def test_firings_past_the_retention_limit_go_and_those_inside_it_stay(db_url: str) -> None:
    alana = owner(db_url)
    fake = FakeHeld()

    async def scenario() -> None:
        async with world(db_url, FakeHouse(), SETTINGS):
            services.register(HeldStates, fake)
            try:
                bench = await running(alana)
                await tick()
                old, fresh = NOW - timedelta(seconds=SETTINGS.keep_s + 1), NOW - timedelta(seconds=SETTINGS.keep_s - 1)
                for context, at in (("old", old), ("fresh", fresh)):
                    await fake.told(alana.household_id, event("ashley_shadow", {"bench": bench, "piece": 1, "version": 1},
                                                             context, at))
                counts = await tick()
                assert counts["pruned"] == 1
                seen = (await services.get(Shadows).of_bench(alana.household_id, bench))[1]
                assert [f.at for f in seen.firings] == [fresh]
            finally:
                services.unregister(HeldStates)
    run(scenario())


def test_a_run_whose_end_has_come_is_undone_as_its_person_and_leaves_the_house(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()

    async def scenario() -> None:
        async with world(db_url, house, replace(SETTINGS, keep_s=864000)):
            services.register(HeldStates, FakeHeld())
            try:
                bench = await running(alana)
                assert len(house.configs) == 1
                early = await tick(NOW)
                assert early["ended"] == 0 and len(house.configs) == 1
                counts = await tick(datetime.now(UTC) + timedelta(days=2))
                assert counts["ended"] == 1 and counts["refused"] == 0 and house.configs == {}
                assert (await services.get(Shadows).of_bench(alana.household_id, bench))[1].ended_at is not None
                view = await services.get(Workshop).read(alana, bench)
                assert isinstance(view.recent[-1].command, Undo) and view.recent[-1].by.person_id == alana.person_id
                again = await tick(datetime.now(UTC) + timedelta(days=3))
                assert again["ended"] == 0
            finally:
                services.unregister(HeldStates)
    run(scenario())


def test_an_end_the_bench_refuses_still_ends_the_run_and_leaves_the_shadow_in_the_house(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()

    async def scenario() -> None:
        async with world(db_url, house, SETTINGS):
            services.register(HeldStates, FakeHeld())
            try:
                bench = await running(alana)
                await services.get(Workshop).close(alana, bench)
                counts = await tick(datetime.now(UTC) + timedelta(days=2))
                assert counts["refused"] == 1 and counts["ended"] == 0 and len(house.configs) == 1
                assert (await services.get(Shadows).of_bench(alana.household_id, bench))[1].ended_at is not None
            finally:
                services.unregister(HeldStates)
    run(scenario())


def test_a_house_out_of_reach_is_counted_and_the_pass_still_ends_what_is_due(db_url: str) -> None:
    alana = owner(db_url)
    house = FakeHouse()
    fake = FakeHeld(down={alana.household_id})

    async def scenario() -> None:
        async with world(db_url, house, SETTINGS):
            services.register(HeldStates, fake)
            try:
                bench = await running(alana)
                assert (await tick())["unreachable"] == 1
                counts = await tick(datetime.now(UTC) + timedelta(days=2))
                assert counts["unreachable"] == 1 and counts["ended"] == 1 and house.configs == {}
                assert bench
            finally:
                services.unregister(HeldStates)
    run(scenario())

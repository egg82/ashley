"""Her skill tools on a bench (`BenchSkillTools`): what they offer, the skill that loads beside them, setting a kind,
reading, editing and rolling back, pinned kinds, refusals as error results, and households apart."""

import json

import pytest
from contract.conversations_support import run
from skills_blind_support import (
    CODE,
    at_info,
    bench_with,
    call,
    data,
    events,
    instructions,
    tools_env,
    tools_of,
    world,
)

from ashley.skills.skills import Skills

# --- the catalogue -----------------------------------------------------------------------------------------------


def test_the_catalogue_offers_bench_work_and_the_skill_tools(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (_, workshop):
            t = tools_of(w.alana, await bench_with(workshop, w.alana))
            specs = {s.name: s for s in (await t.catalogue()).specs}
            assert set(specs) == {"bench_work", "skill_read", "skill_edit", "skill_rollback"}
            assert specs["skill_read"].reads is True
            assert specs["skill_edit"].reads is False and specs["bench_work"].reads is False
            work, edit_spec = specs["bench_work"].parameters, specs["skill_edit"].parameters
            assert json.dumps(work["properties"], sort_keys=True).count('"description"') >= 1
            assert sorted(json.loads(json.dumps(work["properties"]))) == ["label", "work"]
            assert work["required"] == ["work"]
            assert sorted(json.loads(json.dumps(edit_spec["required"]))) == ["base_version", "body", "what", "why"]

    run(scenario())


def test_guidance_names_the_households_kinds_and_a_bench_with_no_kind_loads_no_skill(
        db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    at_info(caplog)
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (s, workshop):
            await s.add_kind(w.alana.household_id, "garden", "Garden planning")
            text = await instructions(tools_of(w.alana, await bench_with(workshop, w.alana)))
            assert "garden" in text and "Garden planning" in text and "code" in text
            assert CODE.body not in text
            other = await instructions(tools_of(w.zed, await bench_with(workshop, w.zed)))
            assert "garden" not in other and "Garden planning" not in other

    run(scenario())
    assert events(caplog, "skills.loaded") == []


def test_the_benchs_skill_loads_into_its_instructions_with_a_log_line(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    at_info(caplog)
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (_, workshop):
            bench = await bench_with(workshop, w.alana, "code")
            text = await instructions(tools_of(w.alana, bench))
            assert CODE.body in text
            assert "code" in text
            logged = events(caplog, "skills.loaded")
            assert len(logged) == 1
            assert (logged[0]["bench"], logged[0]["kind"], logged[0]["version"]) == (bench, "code", 0)

    run(scenario())


def test_the_loaded_text_is_the_households_latest_live_version_not_a_waiting_one(
        db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    at_info(caplog)
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (s, workshop):
            bench = await bench_with(workshop, w.alana, "code")
            await s.edit(w.alana.household_id, "code", "LIVE-TWO", "w", "y", 0, None, w.alana.person_id)
            await s.pin(w.alana.household_id, "code", True)
            await s.edit(w.alana.household_id, "code", "WAITING-THREE", "w", "y", 1, None, None)
            t = tools_of(w.alana, bench)
            text = await instructions(t)
            assert "LIVE-TWO" in text and "WAITING-THREE" not in text and CODE.body not in text
            assert events(caplog, "skills.loaded")[-1]["version"] == 1

    run(scenario())


def test_an_edit_reaches_the_next_catalogue_and_a_sam_on_the_same_household_sees_it(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (_, workshop):
            bench = await bench_with(workshop, w.alana, "code")
            t = tools_of(w.alana, bench)
            assert CODE.body in await instructions(t)
            data(await t.call(call("skill_edit", body="NEW-METHOD", base_version=0, what="w", why="y")))
            text = await instructions(t)
            assert "NEW-METHOD" in text and CODE.body not in text
            sams = await bench_with(workshop, w.sam, "code")
            assert "NEW-METHOD" in await instructions(tools_of(w.sam, sams))
            zeds = await bench_with(workshop, w.zed, "code")
            assert CODE.body in await instructions(tools_of(w.zed, zeds))

    run(scenario())


def test_the_catalogue_survives_the_skills_or_the_bench_being_unreachable(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    at_info(caplog)
    w = world(db_url)

    async def scenario() -> None:
        from ashley import services

        async with tools_env(db_url) as (_, workshop):
            bench = await bench_with(workshop, w.alana, "code")
            services.register(Skills, Skills.null())
            got = await tools_of(w.alana, bench).catalogue()
            assert {s.name for s in got.specs} == {"bench_work", "skill_read", "skill_edit", "skill_rollback"}
            assert CODE.body not in (got.instructions or "")
            gone = await tools_of(w.alana, 999_999).catalogue()
            assert gone.specs and CODE.body not in (gone.instructions or "")

    run(scenario())
    assert events(caplog, "skills.unavailable")


def test_another_households_bench_loads_no_skill(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (_, workshop):
            bench = await bench_with(workshop, w.alana, "code")
            text = await instructions(tools_of(w.zed, bench))
            assert CODE.body not in text

    run(scenario())


# --- bench_work --------------------------------------------------------------------------------------------------


def test_bench_work_sets_the_kind_and_hands_back_the_method(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (_, workshop):
            bench = await bench_with(workshop, w.alana)
            got = data(await tools_of(w.alana, bench).call(call("bench_work", work="code")))
            assert got["work"] == "code"
            assert got["method"]["version"] == 0 and got["method"]["text"] == CODE.body
            assert (await workshop.read(w.alana, bench)).bench.work == "code"

    run(scenario())


def test_bench_work_with_a_label_starts_a_new_kind_and_sets_it(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (s, workshop):
            bench = await bench_with(workshop, w.alana)
            got = data(await tools_of(w.alana, bench).call(call("bench_work", work="electronics", label="Electronics")))
            assert got["work"] == "electronics" and "method" not in got
            assert (await workshop.read(w.alana, bench)).bench.work == "electronics"
            assert {k.kind: k.label for k in await s.kinds(w.alana.household_id)}["electronics"] == "Electronics"
            assert "electronics" not in {k.kind for k in await s.kinds(w.zed.household_id)}

    run(scenario())


def test_bench_work_of_an_unknown_kind_without_a_label_changes_nothing(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (s, workshop):
            bench = await bench_with(workshop, w.alana, "code")
            result = await tools_of(w.alana, bench).call(call("bench_work", work="electronics"))
            assert result.is_error
            assert (await workshop.read(w.alana, bench)).bench.work == "code"
            assert "electronics" not in {k.kind for k in await s.kinds(w.alana.household_id)}

    run(scenario())


@pytest.mark.parametrize("work", ["Not A Slug", "", "x" * 41, "-lead"])
def test_bench_work_of_a_name_that_is_not_a_slug_is_an_error_result(db_url: str, work: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (s, workshop):
            bench = await bench_with(workshop, w.alana)
            result = await tools_of(w.alana, bench).call(call("bench_work", work=work, label="Label"))
            assert result.is_error
            assert (await workshop.read(w.alana, bench)).bench.work is None
            assert {k.kind for k in await s.kinds(w.alana.household_id)} == {"code"}

    run(scenario())


def test_bench_work_none_clears_the_kind(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (_, workshop):
            bench = await bench_with(workshop, w.alana, "code")
            got = data(await tools_of(w.alana, bench).call(call("bench_work", work="none")))
            assert got["work"] is None and "method" not in got
            assert (await workshop.read(w.alana, bench)).bench.work is None

    run(scenario())


def test_bench_work_reports_the_live_version_not_the_seed_once_edited(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (s, workshop):
            await s.edit(w.alana.household_id, "code", "EDITED", "w", "y", 0, None, None)
            bench = await bench_with(workshop, w.alana)
            got = data(await tools_of(w.alana, bench).call(call("bench_work", work="code")))
            assert got["method"] == {"version": 1, "text": "EDITED"}

    run(scenario())


def test_bench_work_on_a_bench_that_is_not_theirs_is_an_error_result(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (_, workshop):
            bench = await bench_with(workshop, w.alana)
            result = await tools_of(w.zed, bench).call(call("bench_work", work="code"))
            assert result.is_error
            assert (await workshop.read(w.alana, bench)).bench.work is None

    run(scenario())



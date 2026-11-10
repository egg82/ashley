"""Her skill tools on a bench (`BenchSkillTools`): what they offer, the skill that loads beside them, setting a kind,
reading, editing and rolling back, pinned kinds, refusals as error results, and households apart."""


import pytest
from contract.conversations_support import run
from skills_blind_support import (
    CODE,
    at_info,
    bench_with,
    call,
    data,
    edit,
    events,
    instructions,
    tools_env,
    tools_of,
    world,
)

from ashley.skills.skills import Skills

# --- skill_read --------------------------------------------------------------------------------------------------


def test_skill_read_defaults_to_the_benchs_kind_and_gives_the_whole_picture(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (s, workshop):
            bench = await bench_with(workshop, w.alana, "code")
            t = tools_of(w.alana, bench)
            seed = data(await t.call(call("skill_read")))
            assert (seed["kind"], seed["version"], seed["edits"], seed["pinned"], seed["seeded_from"], seed["body"]) == (
                "code", 0, 0, False, CODE.seeded_from, CODE.body)
            assert seed["changelog"] == []
            await s.edit(w.alana.household_id, "code", "ONE", "W1", "Y1", 0, bench, None)
            await s.edit(w.alana.household_id, "code", "TWO", "W2", "Y2", 1, None, w.alana.person_id)
            await s.pin(w.alana.household_id, "code", True)
            got = data(await t.call(call("skill_read")))
            assert (got["version"], got["edits"], got["pinned"], got["body"], got["seeded_from"]) == (2, 2, True, "TWO", None)
            top, older = got["changelog"]
            assert (top["version"], top["what"], top["why"], top["by"], top["status"]) == (2, "W2", "Y2", "person", "live")
            assert (older["version"], older["by"], older["restored_from"]) == (1, "ashley", None)

    run(scenario())


def test_skill_read_of_another_kind_by_name(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (s, workshop):
            await s.add_kind(w.alana.household_id, "garden", "Garden")
            await s.edit(w.alana.household_id, "garden", "GARDEN-BODY", "w", "y", 0, None, None)
            bench = await bench_with(workshop, w.alana, "code")
            got = data(await tools_of(w.alana, bench).call(call("skill_read", kind="garden")))
            assert (got["kind"], got["body"], got["version"]) == ("garden", "GARDEN-BODY", 1)

    run(scenario())


def test_skill_read_of_a_kind_with_no_skill_yet_is_version_zero_with_no_body(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (s, workshop):
            await s.add_kind(w.alana.household_id, "garden", "Garden")
            bench = await bench_with(workshop, w.alana)
            got = data(await tools_of(w.alana, bench).call(call("skill_read", kind="garden")))
            assert (got["version"], got["edits"], got["body"], got["changelog"]) == (0, 0, None, [])

    run(scenario())


def test_skill_read_with_no_kind_and_a_bench_with_none_is_an_error_result(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (_, workshop):
            result = await tools_of(w.alana, await bench_with(workshop, w.alana)).call(call("skill_read"))
            assert result.is_error

    run(scenario())


def test_skill_read_of_an_unknown_kind_or_another_households_is_an_error_result(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (s, workshop):
            await s.add_kind(w.alana.household_id, "garden", "Garden")
            t = tools_of(w.zed, await bench_with(workshop, w.zed))
            assert (await t.call(call("skill_read", kind="garden"))).is_error
            assert (await t.call(call("skill_read", kind="nope"))).is_error
            assert not (await t.call(call("skill_read", kind="code"))).is_error

    run(scenario())


# --- skill_edit --------------------------------------------------------------------------------------------------


def test_skill_edit_is_live_at_once_and_recorded_as_hers_on_the_bench(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (s, workshop):
            bench = await bench_with(workshop, w.alana, "code")
            got = data(await tools_of(w.alana, bench).call(edit(body="NEW-BODY", what="W", why="Y")))
            assert (got["kind"], got["version"], got["status"]) == ("code", 1, "live")
            assert "waiting_on" not in got
            skill = await s.current(w.alana.household_id, "code")
            assert skill is not None and (skill.body, skill.version) == ("NEW-BODY", 1)
            top = (await s.changelog(w.alana.household_id, "code"))[0]
            assert (top.person_id, top.bench_id, top.what, top.why, top.base_version) == (None, bench, "W", "Y", 0)

    run(scenario())


def test_skill_edit_names_another_kind_when_asked(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (s, workshop):
            await s.add_kind(w.alana.household_id, "garden", "Garden")
            bench = await bench_with(workshop, w.alana, "code")
            data(await tools_of(w.alana, bench).call(edit(kind="garden")))
            garden = await s.current(w.alana.household_id, "garden")
            code = await s.current(w.alana.household_id, "code")
            assert garden is not None and garden.body == "NEW"
            assert code is not None and code.version == 0

    run(scenario())


def test_skill_edit_of_a_pinned_kind_is_a_proposal_and_says_it_waits(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (s, workshop):
            await s.pin(w.alana.household_id, "code", True)
            bench = await bench_with(workshop, w.alana, "code")
            t = tools_of(w.alana, bench)
            got = data(await t.call(edit()))
            assert got["status"] == "proposed" and got["version"] == 1 and "waiting_on" in got
            text = await instructions(t)
            assert CODE.body in text and "NEW" not in text.replace(CODE.body, "")
            assert "waits" in text
            skill = await s.current(w.alana.household_id, "code")
            assert skill is not None and skill.version == 0 and skill.proposal is not None

    run(scenario())


def test_skill_edit_with_a_stale_base_is_an_error_result_that_says_stale(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (s, workshop):
            bench = await bench_with(workshop, w.alana, "code")
            t = tools_of(w.alana, bench)
            data(await t.call(edit()))
            late = await t.call(edit(body="LATE", base_version=0))
            assert late.is_error and late.content.startswith("stale")
            skill = await s.current(w.alana.household_id, "code")
            assert skill is not None and skill.body == "NEW"

    run(scenario())


@pytest.mark.parametrize("over,outcome", [
    ({"body": ""}, "bad_body"), ({"body": "x" * 16001}, "bad_body"), ({"what": ""}, "bad_note"),
    ({"why": "x" * 301}, "bad_note"), ({"body": "SEED"}, "unchanged"), ({"kind": "nope"}, "unknown_kind")])
def test_skill_edit_refusals_are_error_results_named_by_reason(db_url: str, over: dict[str, object], outcome: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (s, workshop):
            fixed = dict(over)
            if fixed.get("body") == "SEED":
                fixed["body"] = CODE.body
            bench = await bench_with(workshop, w.alana, "code")
            result = await tools_of(w.alana, bench).call(edit(**fixed))
            assert result.is_error and result.content.startswith(outcome), result.content
            skill = await s.current(w.alana.household_id, "code")
            assert skill is not None and skill.version == 0

    run(scenario())


@pytest.mark.parametrize("over", [{"base_version": "0"}, {"base_version": True}, {"base_version": 0.0}, {"body": 5},
                                  {"what": None}, {"extra": 1}])
def test_skill_edit_with_wrongly_typed_or_extra_arguments_is_an_error_result(db_url: str, over: dict[str, object]) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (s, workshop):
            bench = await bench_with(workshop, w.alana, "code")
            result = await tools_of(w.alana, bench).call(edit(**over))
            assert result.is_error
            skill = await s.current(w.alana.household_id, "code")
            assert skill is not None and skill.version == 0

    run(scenario())


def test_skill_edit_with_a_missing_argument_is_an_error_result(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (_, workshop):
            t = tools_of(w.alana, await bench_with(workshop, w.alana, "code"))
            for gone in ("body", "base_version", "what", "why"):
                args: dict[str, object] = {"body": "N", "base_version": 0, "what": "w", "why": "y"}
                del args[gone]
                assert (await t.call(call("skill_edit", **args))).is_error, gone

    run(scenario())


def test_skill_edit_with_a_nul_is_an_error_result_not_a_crash(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (_, workshop):
            t = tools_of(w.alana, await bench_with(workshop, w.alana, "code"))
            assert (await t.call(edit(body="a\x00b"))).is_error
            assert (await t.call(edit(why="a\x00b"))).is_error

    run(scenario())


# --- skill_rollback ----------------------------------------------------------------------------------------------


def test_skill_rollback_to_the_seed_is_a_new_live_version(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (s, workshop):
            bench = await bench_with(workshop, w.alana, "code")
            t = tools_of(w.alana, bench)
            data(await t.call(edit()))
            got = data(await t.call(call("skill_rollback", to_version=0, why="worse")))
            assert (got["kind"], got["version"], got["status"]) == ("code", 2, "live")
            skill = await s.current(w.alana.household_id, "code")
            assert skill is not None and (skill.body, skill.version) == (CODE.body, 2)
            top = (await s.changelog(w.alana.household_id, "code"))[0]
            assert (top.restored_from, top.why, top.person_id, top.bench_id) == (0, "worse", None, bench)

    run(scenario())


def test_skill_rollback_of_a_pinned_kind_waits(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (s, workshop):
            bench = await bench_with(workshop, w.alana, "code")
            t = tools_of(w.alana, bench)
            data(await t.call(edit()))
            await s.pin(w.alana.household_id, "code", True)
            got = data(await t.call(call("skill_rollback", to_version=0, why="worse")))
            assert got["status"] == "proposed" and "waiting_on" in got

    run(scenario())


@pytest.mark.parametrize("args,outcome", [({"to_version": 7, "why": "w"}, "no_such_version"),
                                          ({"to_version": 1, "why": "w"}, "unchanged"),
                                          ({"to_version": 0, "why": ""}, "bad_note"),
                                          ({"to_version": 0, "why": "w", "kind": "nope"}, "unknown_kind")])
def test_skill_rollback_refusals_are_error_results_named_by_reason(db_url: str, args: dict[str, object], outcome: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (_, workshop):
            t = tools_of(w.alana, await bench_with(workshop, w.alana, "code"))
            data(await t.call(edit()))
            result = await t.call(call("skill_rollback", **args))
            assert result.is_error and result.content.startswith(outcome), result.content

    run(scenario())


@pytest.mark.parametrize("args", [{"to_version": "0", "why": "w"}, {"to_version": True, "why": "w"}, {"why": "w"},
                                  {"to_version": 0}, {"to_version": 0, "why": "w", "junk": 1}])
def test_skill_rollback_with_bad_arguments_is_an_error_result(db_url: str, args: dict[str, object]) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (_, workshop):
            t = tools_of(w.alana, await bench_with(workshop, w.alana, "code"))
            assert (await t.call(call("skill_rollback", **args))).is_error

    run(scenario())


# --- unknown tool, unavailability, logging -----------------------------------------------------------------------


def test_an_unknown_tool_is_an_error_result(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (_, workshop):
            result = await tools_of(w.alana, await bench_with(workshop, w.alana)).call(call("skill_delete"))
            assert result.is_error and "skill_delete" in result.content

    run(scenario())


def test_every_tool_answers_with_an_error_result_when_the_skills_are_unreachable(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        from ashley import services

        async with tools_env(db_url) as (_, workshop):
            bench = await bench_with(workshop, w.alana, "code")
            services.register(Skills, Skills.null())
            t = tools_of(w.alana, bench)
            for c in (call("bench_work", work="code"), call("skill_read"), edit(), call("skill_rollback", to_version=0, why="w")):
                result = await t.call(c)
                assert result.is_error and result.call_id == c.id
                assert result.content.startswith("unavailable")

    run(scenario())


def test_a_result_carries_the_call_id(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (_, workshop):
            c = call("skill_read", kind="code")
            assert (await tools_of(w.alana, await bench_with(workshop, w.alana)).call(c)).call_id == c.id

    run(scenario())


def test_calls_log_the_tool_and_outcome_and_never_the_text(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    at_info(caplog)
    w = world(db_url)

    async def scenario() -> None:
        async with tools_env(db_url) as (_, workshop):
            t = tools_of(w.alana, await bench_with(workshop, w.alana, "code"))
            await t.call(edit(body="SECRET-BODY-zq", what="SECRET-WHAT-zq", why="SECRET-WHY-zq"))
            await t.call(call("bench_work", work="secret-kind-zq", label="SECRET-LABEL-zq"))

    run(scenario())
    lines = events(caplog, "tools.call")
    assert [(f["tool"], f["outcome"]) for f in lines] == [("skill_edit", "ok"), ("bench_work", "ok")]
    blob = " ".join(f"{r.getMessage()} {getattr(r, 'fields', {})}" for r in caplog.records)
    assert "SECRET-BODY" not in blob and "SECRET-WHAT" not in blob and "SECRET-LABEL" not in blob

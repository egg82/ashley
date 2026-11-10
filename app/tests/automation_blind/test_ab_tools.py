"""Her automation tools: read the house, bring an automation onto the bench as a body, propose installing, and read where
an install stands. Nothing she calls writes to the house, and she has no tool that installs."""

from ab_support import CONFIG, add, bench_with_piece, crowd, edit, installed, objects, parsed, propose
from ab_support import tool_call, tools_for
from ashley import services
from ashley.home_assistant.homes import Homes
from ashley.workshop.automation_config import config_of
from ashley.workshop.commands import Proposed
from ashley.workshop.install_piece import automation_id_for
from ashley.workshop.model import HER
from ashley.workshop.workshop import Workshop
from automations_support import FakeHouse
from contract.conversations_support import db_url as db_url, run

NAMES = {"house_automations", "house_automation", "bench_propose_install", "bench_install_state"}


def a_house() -> FakeHouse:
    house = FakeHouse()
    house.add("old_porch", "Old porch", on=True, triggers=[{"trigger": "time", "at": "01:00:00"}],
              actions=[{"action": "light.turn_on"}])
    house.add("dim", "Dim hall", on=False)
    house.yaml_only.append("automation.from_yaml")
    return house


def test_the_catalogue_offers_exactly_the_four_tools_while_a_house_is_wired_and_none_otherwise(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url, a_house()) as (_, c):
            bench, _ = await bench_with_piece(c.alana)
            specs = (await tools_for(c.alana, bench).catalogue()).specs
            assert {s.name for s in specs} == NAMES
            services.unregister(Homes)
            assert (await tools_for(c.alana, bench).catalogue()).specs == ()

    run(scenario())


def test_house_automations_lists_each_with_its_id_entity_name_and_whether_it_is_on(db_url: str) -> None:
    async def scenario() -> None:
        house = a_house()
        async with crowd(db_url, house) as (_, c):
            bench, _ = await bench_with_piece(c.alana)
            result = await tools_for(c.alana, bench).call(tool_call("house_automations"))
            assert not result.is_error
            rows = {str(d["entity_id"]): d for d in objects(parsed(result.content)) if "entity_id" in d}
            assert set(rows) == {"automation.old_porch", "automation.dim", "automation.from_yaml"}
            assert rows["automation.old_porch"]["automation_id"] == "old_porch"
            assert rows["automation.old_porch"]["name"] == "Old porch" and rows["automation.dim"]["enabled"] is False
            assert rows["automation.old_porch"]["enabled"] is True
            assert rows["automation.from_yaml"]["automation_id"] is None
            assert house.writes == []

    run(scenario())


def test_house_automation_reads_one_config_as_a_body_without_its_id(db_url: str) -> None:
    async def scenario() -> None:
        house = a_house()
        async with crowd(db_url, house) as (_, c):
            bench, _ = await bench_with_piece(c.alana)
            result = await tools_for(c.alana, bench).call(tool_call("house_automation", automation_id="old_porch"))
            assert not result.is_error and "Old porch" in result.content
            bodies = [d["body"] for d in objects(parsed(result.content)) if "body" in d]
            assert len(bodies) == 1 and isinstance(bodies[0], str)
            config = config_of(bodies[0])
            assert config == {"alias": "Old porch", "triggers": [{"trigger": "time", "at": "01:00:00"}],
                              "actions": [{"action": "light.turn_on"}]}
            assert house.writes == []

    run(scenario())


def test_house_automation_of_an_id_the_house_does_not_have_is_an_error_result(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url, a_house()) as (_, c):
            bench, _ = await bench_with_piece(c.alana)
            result = await tools_for(c.alana, bench).call(tool_call("house_automation", automation_id="nope"))
            assert result.is_error

    run(scenario())


def test_a_house_out_of_reach_is_an_error_result_not_an_exception(db_url: str) -> None:
    async def scenario() -> None:
        house = a_house()
        house.down_after = 0
        async with crowd(db_url, house) as (_, c):
            bench, _ = await bench_with_piece(c.alana)
            tools = tools_for(c.alana, bench)
            assert (await tools.call(tool_call("house_automations"))).is_error
            assert (await tools.call(tool_call("house_automation", automation_id="old_porch"))).is_error

    run(scenario())


def test_bench_propose_install_makes_her_propose_command_and_changes_nothing_in_the_house(db_url: str) -> None:
    async def scenario() -> None:
        house = a_house()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            result = await tools_for(c.alana, bench).call(tool_call(
                "bench_propose_install", piece_id=piece, base_version=1, enabled=True, turn_off="automation.old_porch"))
            assert not result.is_error
            log = await services.get(Workshop).log(c.alana, bench)
            assert [(r.command, r.outcome) for r in log[-1:]] == [
                (propose(piece, 1, True, "automation.old_porch", by=HER), "accepted")]
            view = await services.get(Workshop).read(c.alana, bench)
            assert view.proposals[piece].proposed == Proposed(piece, 1, True, "automation.old_porch")
            assert house.writes == [] and house.enabled["automation.old_porch"] is True

    run(scenario())


def test_bench_propose_install_without_turn_off_proposes_none(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url, a_house()) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            result = await tools_for(c.alana, bench).call(tool_call(
                "bench_propose_install", piece_id=piece, base_version=1, enabled=False))
            assert not result.is_error
            proposed = (await services.get(Workshop).read(c.alana, bench)).proposals[piece].proposed
            assert (proposed.enabled, proposed.turn_off) == (False, None)

    run(scenario())


def test_bench_propose_install_refusals_are_error_results_naming_the_reason_and_are_logged_refused(db_url: str) -> None:
    async def scenario() -> None:
        house = a_house()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            note = (await services.get(Workshop).apply(c.alana, bench, add(c.alana, "x", kind="note"))).piece_id
            draft = (await services.get(Workshop).apply(c.alana, bench, add(c.alana, ""))).piece_id
            tools = tools_for(c.alana, bench)
            cases = {"stale_base": piece, "not_installable": note, "incomplete": draft, "no_such_piece": 99}
            for reason, target in cases.items():
                version = 7 if reason == "stale_base" else 1
                result = await tools.call(tool_call("bench_propose_install", piece_id=target, base_version=version,
                                                    enabled=True))
                assert result.is_error and reason in result.content, (reason, result.content)
            log = await services.get(Workshop).log(c.alana, bench)
            assert [r.outcome for r in log[-4:]] == list(cases)
            assert (await services.get(Workshop).read(c.alana, bench)).proposals == {}
            assert house.writes == []

    run(scenario())


def test_bench_propose_install_turning_off_an_automation_the_house_does_not_have_is_an_error_and_logs_nothing(
        db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url, a_house()) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            before = len(await services.get(Workshop).log(c.alana, bench))
            result = await tools_for(c.alana, bench).call(tool_call(
                "bench_propose_install", piece_id=piece, base_version=1, enabled=True, turn_off="automation.nope"))
            assert result.is_error
            assert len(await services.get(Workshop).log(c.alana, bench)) == before

    run(scenario())


def test_bad_arguments_are_error_results_and_log_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url, a_house()) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            tools = tools_for(c.alana, bench)
            before = len(await services.get(Workshop).log(c.alana, bench))
            for call in (tool_call("bench_propose_install", piece_id=piece, enabled=True),
                         tool_call("bench_propose_install", piece_id="x", base_version=1, enabled=True),
                         tool_call("bench_propose_install", piece_id=piece, base_version=1, enabled=True, install=True),
                         tool_call("house_automation"), tool_call("bench_install_state"),
                         tool_call("bench_install"), tool_call("install_automation", piece_id=piece)):
                assert (await tools.call(call)).is_error, call
            assert len(await services.get(Workshop).log(c.alana, bench)) == before

    run(scenario())


def test_bench_install_state_says_a_proposal_is_waiting_then_how_the_install_went(db_url: str) -> None:
    async def scenario() -> None:
        house = a_house()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            tools = tools_for(c.alana, bench)
            nothing = await tools.call(tool_call("bench_install_state", piece_id=piece))
            assert not nothing.is_error
            await services.get(Workshop).apply(c.alana, bench, propose(piece, 1, True))
            waiting = await tools.call(tool_call("bench_install_state", piece_id=piece))
            assert not waiting.is_error and waiting.content != nothing.content
            await installed(c.alana, bench, piece, enabled=True)
            done = await tools.call(tool_call("bench_install_state", piece_id=piece))
            assert not done.is_error and "done" in done.content and automation_id_for(bench, piece) in done.content
            house.refuse = "no good"
            await services.get(Workshop).apply(c.alana, bench, edit(c.alana, piece, 1, alias="v2"))
            await installed(c.alana, bench, piece, version=2, enabled=True)
            refused = await tools.call(tool_call("bench_install_state", piece_id=piece))
            assert "refused" in refused.content and "no good" in refused.content

    run(scenario())


def test_the_tools_of_another_household_see_no_bench(db_url: str) -> None:
    async def scenario() -> None:
        house = a_house()
        async with crowd(db_url, house) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            tools = tools_for(c.zed, bench)
            result = await tools.call(tool_call("bench_propose_install", piece_id=piece, base_version=1, enabled=True))
            assert result.is_error
            assert (await tools.call(tool_call("bench_install_state", piece_id=piece))).is_error
            assert (await services.get(Workshop).read(c.alana, bench)).proposals == {}

    run(scenario())


def test_a_tool_result_never_carries_the_bodys_config_when_the_call_was_not_a_read(db_url: str) -> None:
    async def scenario() -> None:
        async with crowd(db_url, a_house()) as (_, c):
            bench, piece = await bench_with_piece(c.alana)
            result = await tools_for(c.alana, bench).call(tool_call(
                "bench_propose_install", piece_id=piece, base_version=1, enabled=True))
            assert CONFIG["alias"] not in result.content

    run(scenario())



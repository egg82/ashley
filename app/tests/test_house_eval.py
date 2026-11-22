"""The house eval against fakes: the guard runs a call only when a catalogue offered its spec as a read, each
expectation grades as it says, and steps, the step limit, repeats and the JSON come out right."""

import asyncio
import json
from collections.abc import Sequence

import httpx2
import pytest
from ashley import services
from ashley.channels.respond import LIMITS
from ashley.evals import house, house_live, house_report
from ashley.evals.house import Billed, Seat
from ashley.evals.house_guard import Attempt, GuardedTools, Step
from ashley.evals.house_readonly import ReadOnlyHomes, ReadOnlyHouse
from ashley.connections.model import Connection
from ashley.home_assistant.client import HomeAssistant
from ashley.home_assistant.homes import Home, Homes
from ashley.home_assistant.house import ActionInfo, Performed
from ashley.inference.inference import Inference
from ashley.inference.model import ToolCall, ToolCalls, ToolSpec
from ashley.inference.reply import Reply
from ashley.tools.tools import Tools
from pydantic import BaseModel
from house_double_support import MemoryHouse, state
from money_support import HeldConnections
from respond_support import ALANA, HOME, Fakes, FakeTools, calls, wired as wired

SEAT = Seat(HOME.id, ALANA.id)
ANSWER = Reply(spoken="s", text="t")


async def no_ledger(conversation_id: int, task: str) -> list[Billed]:
    return [Billed(100, "fake", "m")]


def tool(name: str, arguments: dict[str, object] | None = None) -> ToolCall:
    return ToolCall("c", name, arguments or {})


def spec(name: str, reads: bool = False) -> ToolSpec:
    return ToolSpec(name, "", {"type": "object"}, reads=reads)


def guarded(*specs: ToolSpec) -> tuple[GuardedTools, FakeTools]:
    inner = FakeTools(specs=specs)
    guard = GuardedTools(inner)
    asyncio.run(guard.catalogue())
    return guard, inner


def test_a_read_whose_spec_says_it_reads_runs_though_no_list_names_it() -> None:
    guard, inner = guarded(spec("todo_lists", True), spec("house_do"))
    got = asyncio.run(guard.call(tool("todo_lists")))
    assert not got.is_error and [c.name for c in inner.called] == ["todo_lists"] and guard.refused == []


def test_a_change_is_answered_as_done_and_never_reaches_the_inner_tools() -> None:
    guard, inner = guarded(spec("todo_lists", True), spec("house_do"))
    got = asyncio.run(guard.call(tool("house_do", {"action": "light.turn_on", "name": "Lamp"})))
    assert not got.is_error and json.loads(got.content)["done"] is True and inner.called == []
    assert [a.name for a in guard.refused] == ["house_do"]


def test_a_name_no_catalogue_offered_is_kept_from_the_inner_tools() -> None:
    guard, inner = guarded(spec("house_ask", True))
    asyncio.run(guard.call(tool("made_up")))
    assert inner.called == [] and [a.name for a in guard.refused] == ["made_up"]


def test_a_read_first_offered_by_a_later_catalogue_runs() -> None:
    guard, inner = guarded(spec("lights"))
    inner.specs = (spec("lights"), spec("loaded_read", True))
    asyncio.run(guard.catalogue())
    asyncio.run(guard.call(tool("loaded_read")))
    assert [c.name for c in inner.called] == ["loaded_read"] and guard.refused == []


def test_the_house_under_her_per_turn_tools_reads_through_and_keeps_every_change_from_the_real_one() -> None:
    inner = MemoryHouse(things=[state("light.hall", "Hall", "off", "Hall")])
    refused: list[Attempt] = []
    guarded = ReadOnlyHouse(inner, refused)

    async def go() -> None:
        assert [s.id for s in await guarded.states()] == ["light.hall"] and await guarded.records("device") == ()
        await guarded.perform("light.turn_on", ("light.hall",), {})
        assert await guarded.write_config("automation", None, {"alias": "x"}) == "new"
        assert await guarded.delete_config("automation", "x") is True
        assert await guarded.create_record("area", {"name": "x"}) == "new"
        await guarded.update_record("entity", "light.hall", {"name": "y"})
        await guarded.delete_record("device", "d")
    asyncio.run(go())
    assert [a.name for a in refused] == ["house:perform:light.turn_on", "house:write:automation", "house:delete:automation",
                                         "house:create:area", "house:update:entity", "house:delete:device"]
    assert inner.done == []


def test_a_response_only_action_reaches_the_inner_house_and_an_ordinary_one_is_refused() -> None:
    inner = MemoryHouse(catalogue=[ActionInfo("todo.get_items", "", {}, "only"), ActionInfo("light.turn_on", "", {}, "none")],
                        returns={"todo.get_items": {"items": ["milk"]}})
    refused: list[Attempt] = []
    guarded = ReadOnlyHouse(inner, refused)

    async def go() -> tuple[Performed, Performed]:
        return await guarded.perform("todo.get_items", ("todo.list",), {}), await guarded.perform("light.turn_on", ("light.hall",), {})
    read, change = asyncio.run(go())
    assert read.response == {"items": ["milk"]} and change == Performed()
    assert [a.name for a in refused] == ["house:perform:light.turn_on"]
    assert [d[2] for d in inner.done] == ["todo.get_items"]


def test_every_household_gets_the_read_only_house_for_the_run() -> None:
    refused: list[Attempt] = []
    home = Home(1, HomeAssistant(httpx2.AsyncClient(base_url="http://ha.test")), MemoryHouse())
    got = asyncio.run(ReadOnlyHomes(AnyHome(home), refused).of(1))
    assert got is not None and isinstance(got.house, ReadOnlyHouse) and got.household_id == 1


class AnyHome(Homes):
    def __init__(self, home: Home) -> None:
        self._home = home

    async def of(self, household_id: int) -> Home | None:
        return self._home

    async def check(self, base_url: str, token: str) -> None:
        raise NotImplementedError


def run_case(wired: Fakes, case_id: str, script: Sequence[ToolCalls | BaseModel | Exception], runs: int = 1) -> list[house.RunResult]:
    wired.tools.specs = (ToolSpec("house_ask", "", {"type": "object"}, reads=True), ToolSpec("house_do", "", {"type": "object"}))
    wired.inference.script = list(script)
    return asyncio.run(house.run(runs, case_id, SEAT, no_ledger))[case_id]


def test_a_read_only_case_passes_on_reads_and_fails_on_a_write(wired: Fakes) -> None:
    [good] = run_case(wired, "read-shopping-list", [calls("house_ask"), ANSWER])
    assert good.passed and good.steps == 1 and not good.limit_hit and good.tools == ("house_ask",)
    [bad] = run_case(wired, "read-shopping-list", [ToolCalls((tool("house_do"),)), ANSWER])
    assert not bad.passed and bad.refused == ("house_do",)
    assert [c.name for c in wired.tools.called] == ["house_ask"]


def test_an_action_case_passes_on_the_named_tool_and_target_and_the_call_is_still_refused(wired: Fakes) -> None:
    right = ToolCall("a", "house_do", {"action": "todo.add_item", "item": "Paper Towels", "name": "Shopping List"})
    [got] = run_case(wired, "act-shopping-add", [ToolCalls((right,)), ANSWER])
    assert got.passed and got.refused == ("house_do",)
    assert wired.tools.called == []


def test_an_action_case_passes_on_its_write_kept_by_the_read_only_house_not_the_everyday_guard() -> None:
    [case] = [c for c in house.load() if c["id"] == "act-shopping-add"]
    asked = Step("chat", "auto", None, (ToolCall("a", "todo_change", {"list": "todo.shopping", "op": "add", "item": "Paper towels"}),))
    kept = [Attempt("house:perform:todo.add_item", "")]
    assert house.passes(case, kept, [asked])
    other = Step("chat", "auto", None, (ToolCall("a", "todo_change", {"list": "todo.shopping", "op": "add", "item": "bread"}),))
    assert not house.passes(case, kept, [other])


def test_an_action_case_fails_without_the_call_or_on_another_target(wired: Fakes) -> None:
    [none] = run_case(wired, "act-shopping-add", [ANSWER])
    assert not none.passed
    other = ToolCall("a", "house_do", {"action": "todo.add_item", "item": "bread"})
    [wrong] = run_case(wired, "act-shopping-add", [ToolCalls((other,)), ANSWER])
    assert not wrong.passed


def test_an_unknown_name_case_records_repeated_identical_calls_and_the_step_limit(wired: Fakes) -> None:
    limit = LIMITS["chat"].max_tool_rounds
    script: list[ToolCalls | BaseModel | Exception] = [*(ToolCalls((ToolCall(f"r{i}", "house_ask", {}),)) for i in range(limit)), ANSWER]
    [got] = run_case(wired, "unknown-porch-light", script)
    assert got.passed and got.steps == limit and got.limit_hit and got.repeats == limit - 1


def test_a_voice_case_is_asked_as_a_command_and_counted_by_its_own_kind(wired: Fakes) -> None:
    [got] = run_case(wired, "read-temperature", [calls("house_ask"), ANSWER])
    assert got.passed and wired.inference.tasks == ["command", "command"]


def test_services_are_restored_after_a_run(wired: Fakes) -> None:
    run_case(wired, "read-shopping-list", [ANSWER])
    assert services.get(Tools) is wired.tools and services.get(Inference) is wired.inference


def test_an_unknown_case_raises(wired: Fakes) -> None:
    with pytest.raises(ValueError):
        asyncio.run(house.run(1, "nope", SEAT, no_ledger))


def test_the_report_and_json_agree_and_carry_tokens_and_models(wired: Fakes) -> None:
    results = {"read-shopping-list": run_case(wired, "read-shopping-list", [calls("house_ask"), ANSWER], runs=1)}
    data = json.loads(house_report.to_json(results))
    assert data["total"]["runs"] == 1 and data["cases"][0]["runs"][0]["tokens"] == [100]
    assert data["cases"][0]["runs"][0]["models"] == ["fake/m"]
    assert "read-shopping-list" in house_report.render(results) and "TOTAL" in house_report.render(results)


def test_an_action_case_reports_the_round_of_its_write_and_the_totals_leave_its_steps_out(wired: Fakes) -> None:
    right = ToolCall("a", "house_do", {"action": "todo.add_item", "item": "Paper Towels", "name": "Shopping List"})
    script: list[ToolCalls | BaseModel | Exception] = [calls("house_ask"), ToolCalls((right,)), ANSWER]
    results = {"act-shopping-add": run_case(wired, "act-shopping-add", script),
               "read-shopping-list": run_case(wired, "read-shopping-list", [calls("house_ask"), ANSWER])}
    assert results["act-shopping-add"][0].steps_to_write == 2 and results["read-shopping-list"][0].steps_to_write is None
    data = json.loads(house_report.to_json(results))
    assert data["total"]["steps"] == [1] and data["total"]["steps_to_write"] == 2
    assert data["cases"][0]["summary"]["steps"] == [2] and data["cases"][0]["summary"]["steps_to_write"] == [2]


def test_an_action_case_that_never_writes_has_no_round_for_it_and_is_not_in_the_median(wired: Fakes) -> None:
    results = {"act-shopping-add": run_case(wired, "act-shopping-add", [ANSWER])}
    assert results["act-shopping-add"][0].steps_to_write is None
    data = json.loads(house_report.to_json(results))
    assert data["cases"][0]["summary"]["steps_to_write"] == [None] and data["total"]["steps_to_write"] == 0


def test_the_seed_cases_cover_what_was_asked() -> None:
    cases = house.load()
    by = {e: [c for c in cases if c["expect"] == e] for e in ("read_only", "action", "unknown_name")}
    assert len(by["read_only"]) >= 5 and len(by["action"]) >= 3 and len(by["unknown_name"]) >= 3
    assert {c["channel"] for c in cases} == {"chat", "voice"}
    assert all(c["tools"] and c["target"] for c in by["action"])
    assert len({c["id"] for c in cases}) == len(cases)


class Replacing(HeldConnections):
    async def replace(self, connection_id: int, household_id: int, person_id: int, base_url: str,
                      secret: str) -> Connection | None:
        self.connect(household_id, base_url, secret, "home_assistant")
        return self.held[(household_id, "home_assistant")].connection


def _house_of(held: HeldConnections) -> tuple[str, str]:
    opened = held.held[(SEAT.household_id, "home_assistant")]
    return opened.connection.base_url, opened.secret


def test_the_eval_household_gets_the_named_house_as_its_connection() -> None:
    held = Replacing()
    asyncio.run(house_live.connect_house(held, SEAT, "http://ha.eval.test:8123/", "tok"))
    assert _house_of(held) == ("http://ha.eval.test:8123", "tok")


def test_a_connection_the_household_already_holds_is_replaced_by_the_named_house() -> None:
    held = Replacing()
    held.connect(SEAT.household_id, "http://old.test:8123", "old", "home_assistant")
    asyncio.run(house_live.connect_house(held, SEAT, "http://ha.eval.test:8123", "tok"))
    assert _house_of(held) == ("http://ha.eval.test:8123", "tok")


@pytest.mark.parametrize(("url", "token"), [("", "tok"), ("ftp://ha.test", "tok"), ("http://ha.test:8123", "")])
def test_no_address_or_token_is_a_refusal_and_writes_nothing(url: str, token: str) -> None:
    held = Replacing()
    with pytest.raises(ValueError, match="EVAL_HA_URL"):
        asyncio.run(house_live.connect_house(held, SEAT, url, token))
    assert held.held == {}

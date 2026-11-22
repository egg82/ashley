"""The reach eval against fakes: no call off the read allow-list reaches any source of a turn, a run is scored by the
groups she called, the case file is valid and covers the groups, and a variant's cut is what the run's model sees."""

import asyncio
import json
from collections.abc import Sequence

import pytest
from ashley import services
from ashley.channels import cut, turn_tools
from ashley.channels.on_demand import LOADER
from ashley.connections.connections import Connections
from ashley.evals import reach, reach_report, variant
from ashley.evals.house import Billed, Seat
from ashley.inference.inference import Inference
from ashley.evals.reach_guard import Notes, ReachGuard
from ashley.inference.model import ToolCall, ToolCalls, ToolSpec
from ashley.inference.reply import Reply
from ashley.tools.composite import CompositeTools
from pydantic import BaseModel
from money_support import HeldConnections
from respond_support import ALANA, HOME, Fakes, FakeTools, calls, wired as wired

SEAT = Seat(HOME.id, ALANA.id)
ANSWER = Reply(spoken="s", text="t")
READS = reach.reads()


async def no_ledger(conversation_id: int, task: str) -> list[Billed]:
    return [Billed(100, "fake", "m"), Billed(120, "fake", "m")]


def source(*names: str) -> FakeTools:
    return FakeTools(specs=tuple(ToolSpec(n, "", {"type": "object"}) for n in names))


def test_no_tool_of_any_source_of_a_turn_reaches_its_source_unless_it_is_a_listed_read() -> None:
    reading = sorted(READS)[0]
    sources = {"everyday": source("house_do", reading), "money": source("money_categorise", "money_note"),
               "mail": source("mail_send", "mail_draft"), "reminders": source("remind", "remind_on_money"),
               "print_queue": source("print_queue"), "code": source("run_code")}
    guard = ReachGuard(CompositeTools(sources), READS, notes=Notes())
    names = [s.name for s in asyncio.run(guard.catalogue()).specs]
    assert len(names) == 10 and reading in names
    for name in names:
        got = asyncio.run(guard.call(ToolCall("c", name, {})))
        assert not got.is_error
    reached = [c.name for s in sources.values() for c in s.called]
    assert reached == [reading]
    assert sorted(a.name for a in guard.notes.refused) == sorted(n for n in names if n != reading)
    assert guard.notes.offered["money_note"] == "money" and guard.notes.offered["run_code"] == "code"


def test_the_allow_list_holds_no_tool_that_changes_anything() -> None:
    assert READS and not {n for n in READS if "do" in n.split("_") or "change" in n or "send" in n or "categorise" in n}


def run_case(wired: Fakes, case_id: str, script: Sequence[ToolCalls | BaseModel | Exception], runs: int = 1) -> list[reach.RunResult]:
    wired.tools.specs = (ToolSpec("lights", "", {"type": "object"}), ToolSpec("house_ask", "", {"type": "object"}, reads=True))
    wired.inference.script = list(script)
    return asyncio.run(reach.run(runs, case_id, SEAT, no_ledger))[case_id]


def test_a_write_the_model_asks_for_is_scored_by_its_group_and_never_reaches_the_source(wired: Fakes) -> None:
    [got] = run_case(wired, "everyday-light-state", [calls("lights"), ANSWER])
    assert got.passed and got.groups == ("everyday",) and got.extra == () and got.refused == ("lights",)
    assert wired.tools.called == []


def test_a_listed_read_reaches_the_source(wired: Fakes) -> None:
    [got] = run_case(wired, "everyday-light-state", [calls("house_ask"), ANSWER])
    assert got.passed and got.refused == () and [c.name for c in wired.tools.called] == ["house_ask"]


def test_an_ask_that_needs_no_tool_fails_on_a_call_and_names_the_group_it_reached_for(wired: Fakes) -> None:
    [clean] = run_case(wired, "none-joke", [ANSWER])
    assert clean.passed and clean.tools == () and clean.extra == ()
    [reached] = run_case(wired, "none-joke", [calls("lights"), ANSWER])
    assert not reached.passed and reached.extra == ("everyday",)


def test_a_case_without_its_group_fails_naming_what_is_missing_and_what_no_catalogue_held(wired: Fakes) -> None:
    [got] = run_case(wired, "money-balance", [calls("lights"), ANSWER])
    assert not got.passed and got.missing == ("money",) and got.extra == ("everyday",)
    assert got.unoffered == ("money",)


def test_a_named_tool_must_be_called_and_its_group_is_wanted_not_extra() -> None:
    case = {"id": "x", "ask": "a", "groups": [], "tools": ["remind_on_money"]}
    offered = {"remind_on_money": "reminders", "remind": "reminders", "lights": "everyday"}
    assert reach.score(case, ["remind"], offered) == (False, ("remind_on_money",), ())
    assert reach.score(case, ["remind", "remind_on_money", "lights"], offered) == (True, (), ("everyday",))


def test_a_case_with_any_of_passes_on_one_alternative_reached_whole_and_names_what_the_first_nearest_lacks() -> None:
    case = {"id": "x", "ask": "a", "groups": [], "tools": [], "any_of": [["readers"], ["mail", "calendar"]]}
    offered = {"send_readers": "readers", "mail_search": "mail", "calendar_events": "calendar", "lights": "everyday"}
    assert reach.score(case, ["send_readers"], offered) == (True, (), ())
    assert reach.score(case, ["mail_search", "calendar_events"], offered) == (True, (), ())
    assert reach.score(case, ["mail_search"], offered) == (False, ("readers",), ())
    assert reach.score(case, ["lights"], offered) == (False, ("readers",), ("everyday",))
    assert reach.score(case, [], offered) == (False, ("readers",), ())


def test_any_of_names_a_tool_as_well_as_a_group_and_adds_to_the_required() -> None:
    case = {"id": "x", "ask": "a", "groups": ["todo"], "tools": [], "any_of": [["look_up"], ["house_ask"]]}
    offered = {"look_up": "everyday", "house_ask": "everyday", "todo_lists": "todo"}
    assert reach.score(case, ["todo_lists", "house_ask"], offered) == (True, (), ())
    assert reach.score(case, ["house_ask"], offered) == (False, ("todo",), ())


def test_the_saved_baseline_shape_is_scored_again_by_the_case_file() -> None:
    run = {"tools": ["calendar_events", "todo_lists"], "groups": ["calendar", "todo"], "passed": False, "error": None}
    saved = {"cases": [{"id": "readers-clash", "summary": {"passes": 0}, "runs": [run]},
                       {"id": "gone", "summary": {"passes": 0}, "runs": [run]},
                       {"id": "none-joke", "summary": {"passes": 1}, "runs": [{**run, "tools": [], "groups": [], "passed": True}]}]}
    text = reach_report.rescore(saved)
    assert "1/1  (was 0)" in text and "gone" not in text and text.endswith("2/2  (was 1/2)")


def test_steps_tokens_and_models_come_from_the_run(wired: Fakes) -> None:
    [got] = run_case(wired, "calendar-next", [calls("lights"), calls("lights", prefix="d"), ANSWER])
    assert got.steps == 2 and got.tokens == (100, 120) and got.models == ("fake/m",) and not got.limit_hit and got.repeats == 0


def load(*groups: str) -> ToolCalls:
    return ToolCalls((ToolCall("u", LOADER, {"groups": list(groups)}),))


def with_core(*core: str) -> None:
    variant.install(variant.parse(json.dumps({"name": "core", "core": list(core)})))


def test_the_loader_is_neither_a_group_nor_a_tool_call_but_its_step_counts_and_its_groups_are_reported(
        wired: Fakes) -> None:
    with_core("everyday")
    try:
        [got] = run_case(wired, "none-joke", [load("devices"), ANSWER])
    finally:
        variant.install(None)
    assert got.passed and got.tools == () and got.groups == () and got.extra == ()
    assert got.steps == 1 and got.loaded == ("devices",)


def test_a_group_outside_the_core_is_offered_to_the_model_only_after_it_is_loaded(wired: Fakes) -> None:
    with_core("everyday")
    try:
        [got] = run_case(wired, "devices-count", [load("devices"), calls("household_devices"), ANSWER])
    finally:
        variant.install(None)
    offered = [{t.name for t in p.tools} for p in wired.inference.prompts]
    assert "household_devices" not in offered[0] and LOADER in offered[0]
    assert "household_devices" in offered[1] and "household_devices" in offered[2]
    assert got.passed and got.tools == ("household_devices",) and got.loaded == ("devices",) and got.steps == 2


def test_a_group_no_turn_held_is_not_reported_loaded(wired: Fakes) -> None:
    with_core("everyday")
    try:
        [got] = run_case(wired, "none-joke", [load("nothing"), ANSWER])
    finally:
        variant.install(None)
    assert got.loaded == () and got.passed


def test_a_run_that_loaded_is_rescored_like_one_that_did_not_and_the_report_names_what_loaded(wired: Fakes) -> None:
    with_core("everyday")
    try:
        results = {"none-joke": run_case(wired, "none-joke", [load("devices"), ANSWER])}
    finally:
        variant.install(None)
    saved = json.loads(reach_report.to_json(results, "core@1"))
    assert saved["cases"][0]["runs"][0]["loaded"] == ["devices"] and saved["cases"][0]["summary"]["loaded"] == {"devices": 1}
    assert reach_report.rescore(saved).endswith("1/1  (was 1/1)")
    assert "devices" in reach_report.render(results, "core@1").splitlines()[2]


def test_the_services_and_the_turn_tools_are_restored_after_a_run(wired: Fakes) -> None:
    before = turn_tools.for_turn
    run_case(wired, "none-joke", [ANSWER])
    assert turn_tools.for_turn is before and services.get(Inference) is wired.inference


def test_an_unknown_case_raises(wired: Fakes) -> None:
    with pytest.raises(ValueError):
        asyncio.run(reach.run(1, "nope", SEAT, no_ledger))


def test_a_variant_that_cuts_a_group_takes_its_tools_from_the_model_and_the_case_fails(wired: Fakes) -> None:
    variant.install(variant.parse('{"name": "no-everyday", "sources": ["everyday"]}'))
    try:
        [got] = run_case(wired, "everyday-light-state", [ANSWER])
    finally:
        variant.install(None)
    assert not got.passed and got.missing == ("everyday",) and got.tools == ()
    assert "lights" not in {t.name for p in wired.inference.prompts for t in p.tools}
    assert cut.active() == cut.NO_CUT


def test_the_report_and_json_agree_and_carry_the_variant(wired: Fakes) -> None:
    results = {"none-joke": run_case(wired, "none-joke", [calls("lights"), ANSWER]),
               "everyday-light-state": run_case(wired, "everyday-light-state", [calls("lights"), ANSWER])}
    data = json.loads(reach_report.to_json(results, "v@1"))
    assert data["variant"] == "v@1" and data["total"]["runs"] == 2 and data["total"]["passes"] == 1
    assert data["total"]["false_positives"] == 1 and data["total"]["no_tool_runs"] == 1
    assert data["total"]["extra"] == {"everyday": 1} and data["cases"][0]["runs"][0]["tokens"] == [100, 120]
    assert data["cases"][0]["summary"]["tokens_first_median"] == 100
    text = reach_report.render(results, "v@1")
    assert "variant: v@1" in text and "TOTAL" in text and "1/1 no-tool runs called a tool" in text


def test_the_case_file_is_valid_and_covers_the_groups_with_no_tool_asks() -> None:
    cases = reach.load()
    by_group: dict[str, int] = {}
    for c in cases:
        for g in c["groups"]:
            by_group[g] = by_group.get(g, 0) + 1
    main = ("everyday", "reminders", "money", "mail", "watches", "printing", "print_queue", "stock", "calendar", "todo",
            "camera", "code_host", "claude_code", "screen", "browser", "house_change", "devices", "code")
    assert all(by_group.get(g, 0) >= 2 for g in main), by_group
    assert sum(not c["groups"] and not c["tools"] for c in cases) >= 5


def test_every_group_a_case_names_is_a_source_a_turn_builds() -> None:
    services.register(Connections, HeldConnections())
    try:
        built = set(turn_tools.sources(reach.inbound({"ask": "x"}, SEAT), None, 1, None, (1, 1)))
    finally:
        services.unregister(Connections)
    known = built | {"everyday", "readers", "mail", "code", "browser"}
    named = {g for c in reach.load() for g in c["groups"]}
    assert named <= known, named - known


@pytest.mark.parametrize("broken", [
    [{"id": "a", "ask": "x", "groups": []}],
    [{"id": "a", "ask": " ", "groups": [], "tools": []}],
    [{"id": "a", "ask": "x", "groups": "money", "tools": []}],
    [{"id": "a", "ask": "x", "groups": ["m", "m"], "tools": []}],
    [{"id": "a", "ask": "x", "groups": [], "tools": []}, {"id": "a", "ask": "y", "groups": [], "tools": []}],
    [{"id": "a", "ask": "x", "groups": [], "tools": [], "any_of": [["m"]]}],
    [{"id": "a", "ask": "x", "groups": [], "tools": [], "any_of": [["m"], []]}],
    [{"id": "a", "ask": "x", "groups": [], "tools": [], "any_of": [["m"], ["m"]]}],
    [{"id": "a", "ask": "x", "groups": [], "tools": [], "why": " "}],
    [{"id": "a", "ask": "x", "groups": [], "tools": [], "other": 1}]])
def test_a_case_that_is_not_well_formed_is_refused(broken: list[dict[str, object]]) -> None:
    with pytest.raises(ValueError):
        reach.validate(broken)

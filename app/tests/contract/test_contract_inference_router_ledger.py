"""The spend ledger rows `RoutedInference` writes: one per call made with the right outcome, usage, cost and duration;
none for a skipped route; and a ledger that fails costing the caller nothing."""

from decimal import Decimal

import pytest
from ashley import logs
from ashley.inference.routes import TASKS
from ashley.inference.model import Task
from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from ashley.inference.model import Message, Usage
from ashley.inference.catalogue import CatalogueState, ModelCatalogue, PricedCatalogue
from ashley.inference.catalogue_model import ModelFields
from ashley.inference.provider import Failure
from ashley.inference.reply import Reply
from ashley.inference.router import RoutedInference
from ashley.inference.spend import Call
from catalogue_support import flat, of
from conversations_support import events
from inference_tools_support import tool_prompt
from inference_support import (FAILURES, USAGE, USAGE_COST, Clock, FakeLedger, FakeProvider, fail, ok, prompt,
                               refuse, route, router, settle, table)


def ask(inference: RoutedInference, task: Task = "chat") -> Reply:
    return settle(inference.generate(task, prompt("hello"), Reply))


def test_an_answered_call_is_one_ok_row_with_the_providers_usage_the_cost_and_the_duration() -> None:
    clock, ledger = Clock(), FakeLedger()
    a = FakeProvider("alpha", [ok(usage=USAGE, seconds=0.25)], clock)
    ask(router(table([route("alpha", "m1")]), [a], ledger, clock))
    assert ledger.rows == [Call("chat", "alpha", "m1", "ok", USAGE, USAGE_COST, 250)]


@pytest.mark.parametrize("task", TASKS)
def test_the_row_names_the_kind_asked(task: Task) -> None:
    ledger = FakeLedger()
    ask(router(table([route("alpha")]), [FakeProvider("alpha")], ledger), task)
    assert [r.task for r in ledger.rows] == [task]


def test_a_call_that_took_no_time_records_zero_milliseconds_and_a_long_one_its_whole_length() -> None:
    clock, ledger = Clock(), FakeLedger()
    a = FakeProvider("alpha", [ok(seconds=0), ok(seconds=12.5)], clock)
    inference = router(table([route("alpha")]), [a], ledger, clock)
    ask(inference)
    ask(inference)
    assert [r.duration_ms for r in ledger.rows] == [0, 12_500]


@pytest.mark.parametrize("failure", FAILURES)
def test_a_failed_call_is_a_row_with_the_failure_as_its_outcome_and_the_usage_billed_anyway(failure: Failure) -> None:
    billed = Usage(40, 0)
    clock, ledger = Clock(), FakeLedger()
    a = FakeProvider("alpha", [fail(failure, billed, seconds=1.5)], clock)
    with pytest.raises(InferenceUnavailable):
        ask(router(table([route("alpha")]), [a], ledger, clock))
    assert ledger.rows == [Call("chat", "alpha", "m1", failure, billed, Decimal("0.00012"), 1500)]


def test_a_failure_with_no_usage_has_no_usage_and_no_cost_never_zero() -> None:
    ledger = FakeLedger()
    with pytest.raises(InferenceUnavailable):
        ask(router(table([route("alpha")]), [FakeProvider("alpha", [fail("unavailable", None)])], ledger))
    assert ledger.rows[0].usage is None
    assert ledger.rows[0].cost_usd is None


def test_a_failure_with_usage_is_priced_like_any_call() -> None:
    """Control for the previous test: with usage, the same model does have a cost."""
    ledger = FakeLedger()
    with pytest.raises(InferenceUnavailable):
        ask(router(table([route("alpha")]), [FakeProvider("alpha", [fail("error", USAGE)])], ledger))
    assert ledger.rows[0].cost_usd == USAGE_COST


def test_a_refusal_is_a_refused_row_with_its_usage_and_cost() -> None:
    clock, ledger = Clock(), FakeLedger()
    a = FakeProvider("alpha", [refuse(USAGE, seconds=2)], clock)
    with pytest.raises(InferenceRefused):
        ask(router(table([route("alpha")]), [a], ledger, clock))
    assert ledger.rows == [Call("chat", "alpha", "m1", "refused", USAGE, USAGE_COST, 2000)]


def test_a_model_with_no_price_records_its_usage_and_a_null_cost() -> None:
    ledger = FakeLedger()
    ask(router(table([route("alpha", "unpriced-model")]), [FakeProvider("alpha")], ledger))
    assert ledger.rows[0].usage == USAGE
    assert ledger.rows[0].cost_usd is None


def test_a_provider_with_no_price_table_records_a_null_cost() -> None:
    ledger = FakeLedger()
    ask(router(table([route("unpriced-provider")]), [FakeProvider("unpriced-provider")], ledger))
    assert ledger.rows[0].cost_usd is None


def test_the_cost_is_priced_by_the_providers_name_and_the_routes_model() -> None:
    ledger = FakeLedger()
    inference = router(table([route("beta", "m1")], overrides={"command": [route("alpha", "m2")]}),
                       [FakeProvider("alpha"), FakeProvider("beta")], ledger)
    ask(inference, "chat")
    ask(inference, "command")
    assert [(r.provider, r.model, r.cost_usd) for r in ledger.rows] == [
        ("beta", "m1", USAGE_COST), ("alpha", "m2", USAGE_COST)]


def test_one_row_per_call_made_in_the_order_made_and_none_for_skipped_routes() -> None:
    ledger = FakeLedger()
    providers = [FakeProvider("alpha", [fail("unavailable")]), FakeProvider("beta", [fail("error"), ok()])]
    inference = router(table([route("ghost"), route("alpha"), route("beta", "m1"), route("beta", "m2")]),
                       providers, ledger)
    ask(inference)
    assert [(r.provider, r.model, r.outcome) for r in ledger.rows] == [
        ("alpha", "m1", "unavailable"), ("beta", "m1", "error"), ("beta", "m2", "ok")]


def test_a_call_is_recorded_before_generate_returns() -> None:
    ledger = FakeLedger()
    inference = router(table([route("alpha")]), [FakeProvider("alpha")], ledger)
    for n in (1, 2, 3):
        ask(inference)
        assert len(ledger.rows) == n


# --- a ledger that fails ----------------------------------------------------------------------------------------


def test_a_failing_ledger_still_returns_the_reply_and_logs_spend_unrecorded(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    ledger = FakeLedger(fail_with=RuntimeError("the table is gone"))
    capsys.readouterr()
    got = ask(router(table([route("alpha")]), [FakeProvider("alpha", [ok("still here")])], ledger))
    assert got.text == "still here"
    assert ledger.attempts == 1
    assert len(events(capsys.readouterr().out, "inference.spend_unrecorded")) == 1


def test_a_failing_ledger_does_not_stop_the_next_route_being_tried() -> None:
    ledger = FakeLedger(fail_with=OSError("disk"))
    a, b = FakeProvider("alpha", [fail("error")]), FakeProvider("beta", [ok("from b")])
    assert ask(router(table([route("alpha"), route("beta")]), [a, b], ledger)).text == "from b"
    assert ledger.attempts == 2


def test_a_failing_ledger_turns_neither_a_refusal_nor_unavailability_into_something_else(
        capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    ledger = FakeLedger(fail_with=RuntimeError("down"))
    with pytest.raises(InferenceRefused):
        ask(router(table([route("alpha")]), [FakeProvider("alpha", [refuse()])], ledger))
    with pytest.raises(InferenceUnavailable):
        ask(router(table([route("beta")]), [FakeProvider("beta", [fail("error")])], ledger))
    assert len(events(capsys.readouterr().out, "inference.spend_unrecorded")) == 2


def test_a_working_ledger_logs_no_spend_unrecorded(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    ask(router(table([route("alpha")]), [FakeProvider("alpha")], FakeLedger()))
    out = capsys.readouterr().out
    assert events(out, "inference.spend_unrecorded") == []
    assert len(events(out, "inference.call")) == 1, "control: the logger is capturing"


# --- the catalogue a call is priced from --------------------------------------------------------------------------

MILLION = Usage(1_000_000, 0)


class Swapping(ModelCatalogue):
    """A catalogue whose layers a test swaps; counts each refresh."""

    def __init__(self, first: ModelCatalogue) -> None:
        self.current = first
        self.refreshes = 0

    async def refresh(self) -> None:
        self.refreshes += 1

    def priced(self) -> PricedCatalogue:
        return self.current.priced()

    async def state(self) -> CatalogueState:
        return await self.current.state()


def test_each_call_is_priced_from_the_catalogue_as_it_is_then_after_a_refresh() -> None:
    swapping, ledger = Swapping(of({"alpha": {"m1": flat("1")}})), FakeLedger()
    inference = router(table([route("alpha")]), [FakeProvider("alpha", [ok(usage=MILLION)] * 3)], ledger,
                       prices=swapping)
    ask(inference)
    swapping.current = of({"alpha": {"m1": flat("4")}})
    ask(inference)
    ask(inference)
    assert [r.cost_usd for r in ledger.rows] == [Decimal(1), Decimal(4), Decimal(4)]
    assert swapping.refreshes == 3


def test_failed_and_refused_calls_are_priced_too() -> None:
    ledger = FakeLedger()
    inference = router(table([route("alpha")]), [FakeProvider("alpha", [fail("error", MILLION), refuse(MILLION)])],
                       ledger, prices=of({"alpha": {"m1": flat("4")}}))
    with pytest.raises(InferenceUnavailable):
        ask(inference)
    with pytest.raises(InferenceRefused):
        ask(inference)
    assert [r.cost_usd for r in ledger.rows] == [Decimal(4), Decimal(4)]


@pytest.mark.parametrize("listed", [{}, {"alpha": {"m2": flat()}}, {"alpha": {"m1": flat("0", "0", "0", "0")}}],
                         ids=["no provider", "not the model", "listed as zero"])
def test_a_model_with_no_known_price_records_its_usage_and_a_null_cost(listed: dict[str, dict[str, ModelFields]]) -> None:
    ledger = FakeLedger()
    ask(router(table([route("alpha")]), [FakeProvider("alpha", [ok(usage=MILLION)])], ledger, prices=of(listed)))
    assert ledger.rows[0].usage == MILLION and ledger.rows[0].cost_usd is None


def test_a_step_with_tools_skips_a_model_listed_without_tool_calls(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    listed = of({"alpha": {"m1": flat(tool_call=False)}, "beta": {"m1": flat()}})
    a, b = FakeProvider("alpha", [ok(), ok()]), FakeProvider("beta", [ok()])
    inference = router(table([route("alpha"), route("beta")]), [a, b], FakeLedger(), prices=listed)
    settle(inference.step("chat", tool_prompt(Message("person", "lights")), Reply))
    assert (len(a.asked), len(b.asked)) == (0, 1)
    skipped = events(capsys.readouterr().out, "inference.route_skipped")
    assert [(e["provider"], e["reason"]) for e in skipped] == [("alpha", "no_tool_calls")]
    ask(inference)
    assert len(a.asked) == 1, "a call offering no tools still uses it"


def test_a_step_with_tools_uses_a_model_the_catalogue_does_not_list() -> None:
    a = FakeProvider("alpha", [ok()])
    inference = router(table([route("alpha")]), [a], FakeLedger(), prices=of({}))
    settle(inference.step("chat", tool_prompt(Message("person", "lights")), Reply))
    assert len(a.asked) == 1

"""The rows shown beside her reply on a bench (`Receipts.facts`), through `Landing.closing` over the real
Workshop: each choice row once, again only after its value changes, and a guessed number an unconfirmed check of the
turn's run rests on, once, by its value and unit; none for a reply she keeps to herself (and those wait for
the next turn); the same ones when a steered turn closes again; none from a piece a tainted turn wrote; carried into
her history as the app's line, on the wire with their options, and read back from receipts stored before them."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime

from ashley import services
from ashley.api.receipt_models import wire_receipts
from ashley.channels.history_receipts import line
from ashley.channels.landing import Landing
from ashley.channels.limits import load as load_limits
from ashley.channels.model import Inbound
from ashley.conversations.model import Fact, Receipt, Receipts
from ashley.db.pool import PoolDatabase
from ashley.inference.reply import Reply
from ashley.live.live import Live
from ashley.runs.model import BenchRun, Output, Run
from ashley.runs.runs import NullRuns, Runs, RunsUnavailable
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Add, Edit
from ashley.workshop.model import HER, By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run
from live_support import FakeLive

LIMITS = load_limits()
SAID = Reply(spoken="Done.", text="Done.")
QUIET = Reply(spoken="Done.", text="Done.", says="none")
FORM = Fact(0, 1, "form", "The lanyard", "flat strap", ("flat strap", "round cord"))


def body(form: str) -> str:
    return json.dumps({"items": [
        {"kind": "choice", "name": "form", "label": "The lanyard", "value": form, "options": ["flat strap", "round cord"],
         "source": "guessed"},
        {"name": "width", "value": 12, "unit": "mm", "source": "guessed"}]})


def on_bench(owner: Owner, bench: int) -> Inbound:
    return Inbound(household_id=owner.household_id, thread=f"bench:{bench}", text="go on", kind="brainstorm",
                   medium="text", audience="owner", speaker_id=owner.person_id, shared=False, place=None, channel="web",
                   bench_id=bench)


def facts(landing: Landing) -> list[tuple[int, int, str, str, str, tuple[str, ...]]]:
    got = landing.receipts
    return [] if got is None else [(f.bench_id, f.piece_id, f.name, f.label, f.value, f.options) for f in got.facts]


def bench_world(db_url: str, scenario: Callable[[Owner, int, Workshop], Awaitable[None]]) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))

    async def go() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        services.register(Live, FakeLive())
        services.register(Workshop, PostgresWorkshop(database, workshop_rules.load()))
        try:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "clip")
            added = await shop.apply(alana, bench.id, Add(HER, "measurements", Text("m", body("flat strap")), "small"))
            assert added.outcome == "accepted"
            await scenario(alana, bench.id, shop)
        finally:
            await database.close()

    run(go())


def test_each_choice_is_shown_beside_one_reply_and_again_only_once_it_changes(db_url: str) -> None:
    async def scenario(alana: Owner, bench: int, shop: Workshop) -> None:
        first = Landing(on_bench(alana, bench), (1, 1), LIMITS)
        assert await first.closing(SAID) == SAID
        assert facts(first) == [(bench, 1, "form", "The lanyard", "flat strap", ("flat strap", "round cord"))]
        assert await first.closing(SAID) == SAID and facts(first) == facts(first)
        assert first.receipts is not None and len(first.receipts.facts) == 1
        second = Landing(on_bench(alana, bench), (1, 2), LIMITS)
        await second.closing(SAID)
        assert second.receipts is None
        assert (await shop.apply(alana, bench, Edit(HER, 1, 1, Text("m", body("round cord"))))).outcome == "accepted"
        third = Landing(on_bench(alana, bench), (1, 3), LIMITS)
        await third.closing(SAID)
        assert [f[4] for f in facts(third)] == ["round cord"]

    bench_world(db_url, scenario)


class _TurnRuns(NullRuns):
    def __init__(self, runs: list[Run] | None) -> None:
        self._runs = runs

    async def bench_runs_of_turn(self, household_id: int, turn_id: int) -> list[Run]:
        if self._runs is None:
            raise RunsUnavailable()
        return [r for r in self._runs if r.turn_id == turn_id]


def _model_run(bench: int, piece: int, turn: int, rests_on: list[str]) -> Run:
    report = {"unit": "mm", "parts": [], "triangles": 0, "checks": [
        {"name": "fits", "actual": 2.0, "op": ">=", "target": 1.0, "tolerance": 0.0, "rests_on": rests_on}]}
    output = Output("ran", 0, "", "", False, {"out/report.json": json.dumps(report)}, ())
    files = {"measurements.json": json.dumps({"items": [{"name": "width", "value": 12, "unit": "mm", "source": "guessed"}]})}
    now = datetime.now(UTC)
    return Run(1, 1, 1, turn, "c", "build123d", "s", "", files, now, now, output, BenchRun(bench, 3, piece, 1))


def test_a_guessed_number_a_check_of_the_turns_run_is_unconfirmed_on_is_shown_once(db_url: str) -> None:
    async def scenario(alana: Owner, bench: int, shop: Workshop) -> None:
        services.register(Runs, _TurnRuns([_model_run(bench, 2, 1, ["width"])]))
        first = Landing(on_bench(alana, bench), (1, 1), LIMITS)
        await first.closing(SAID)
        assert [f[2:] for f in facts(first)] == [("form", "The lanyard", "flat strap", ("flat strap", "round cord")),
                                                 ("width", "width", "12 mm", ())]
        assert await first.closing(SAID) == SAID and len(facts(first)) == 2
        again = Landing(on_bench(alana, bench), (1, 2), LIMITS)
        services.register(Runs, _TurnRuns([_model_run(bench, 2, 2, ["width"])]))
        await again.closing(SAID)
        assert again.receipts is None

    bench_world(db_url, scenario)


def test_a_number_no_unconfirmed_check_rests_on_is_not_shown_and_unreadable_runs_leave_the_choices(db_url: str) -> None:
    async def scenario(alana: Owner, bench: int, shop: Workshop) -> None:
        services.register(Runs, _TurnRuns(None))
        lost = Landing(on_bench(alana, bench), (1, 1), LIMITS)
        await lost.closing(SAID)
        assert [f[2] for f in facts(lost)] == ["form"]
        services.register(Runs, _TurnRuns([_model_run(bench, 2, 2, [])]))
        quiet = Landing(on_bench(alana, bench), (1, 2), LIMITS)
        await quiet.closing(SAID)
        assert quiet.receipts is None

    bench_world(db_url, scenario)


def test_a_reply_she_keeps_to_herself_shows_none_and_they_wait_for_the_next_one(db_url: str) -> None:
    async def scenario(alana: Owner, bench: int, shop: Workshop) -> None:
        quiet = Landing(on_bench(alana, bench), (1, 1), LIMITS)
        assert (await quiet.closing(QUIET)).says == "none" and quiet.receipts is None
        said = Landing(on_bench(alana, bench), (1, 2), LIMITS)
        await said.closing(SAID)
        assert [f[2] for f in facts(said)] == ["form"]

    bench_world(db_url, scenario)


def test_a_piece_a_tainted_turn_wrote_shows_nothing_and_a_turn_off_a_bench_shows_nothing(db_url: str) -> None:
    async def scenario(alana: Owner, bench: int, shop: Workshop) -> None:
        tainted = By(None, outside=True)
        assert (await shop.apply(alana, bench, Edit(tainted, 1, 1, Text("m", body("round cord"))))).outcome == "accepted"
        landing = Landing(on_bench(alana, bench), (1, 1), LIMITS)
        await landing.closing(SAID)
        assert landing.receipts is None
        chat = Landing(replace(on_bench(alana, bench), thread=f"person:{alana.person_id}:web", bench_id=None,
                               kind="chat"), (1, 2), LIMITS)
        await chat.closing(SAID)
        assert chat.receipts is None

    bench_world(db_url, scenario)


def test_facts_reach_her_history_and_the_wire_and_old_receipts_read_with_none() -> None:
    shown = Receipts(facts=(FORM,))
    assert line(shown).endswith("The lanyard: flat strap")
    assert "The lanyard: flat strap" not in line(Receipts((Receipt("Turned on a light"),)))
    wired = wire_receipts(shown)
    assert wired is not None and [(f.label, f.value, f.option_values) for f in wired.choice_rows] == [
        ("The lanyard", "flat strap", ["flat strap", "round cord"])]
    assert Receipts.from_json(shown.to_json()) == shown
    old = {"done": [{"headline": "Turned on a light", "detail": None, "why": None}], "held": [], "proposal_id": None}
    assert Receipts.from_json(old) == Receipts((Receipt("Turned on a light"),))

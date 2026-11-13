"""The bench replay's measures over a synthetic record: each measure reads what its contract says, and a planted wrong
implementation of each (`MUTANTS`) turns a measure the fixture pins wrong, so every expectation here is able to fail."""

import json
from collections.abc import Mapping
from dataclasses import asdict, replace
from typing import Any

import pytest
from ashley.evals import bench_replay_measures as m
from ashley.evals.bench_replay_grader import Verdict
from ashley.evals.bench_replay_measures import Record
from ashley.evals.bench_replay_snapshot import Command, Look, Said
from ashley.tools.bench_replay_world import Finished


def rows(*items: tuple[str, float, str, str]) -> str:
    return json.dumps({"items": [{"name": n, "value": v, "unit": "mm", "source": s, "ref": r} for n, v, s, r in items]})


BEFORE = rows(("a", 5, "guessed", "ga"), ("b", 10, "measured", "mb"), ("c", 3, "guessed", "gc"))
AFTER = rows(("a", 6, "guessed", "ga"), ("b", 12, "measured", "mb"), ("c", 4, "measured", "said"))


def added(seq: int, at: float, kind: str, body: str, person: bool = False) -> Command:
    piece = {"id": seq, "kind": kind, "title": kind, "body": body, "version": 1}
    return Command(seq, at, person, False, {"type": "add", "kind": kind, "body": body}, "accepted",
                   {"type": "added", "piece": piece})


def edited(seq: int, at: float, piece: int, before: str, after: str) -> Command:
    return Command(seq, at, False, False, {"type": "edit", "piece_id": piece, "body": after}, "accepted",
                   {"type": "edited", "piece_id": piece, "before": {"body": before}, "after": {"body": after}})


def ran(seq: int, at: float, piece: int = 2) -> Command:
    return Command(seq, at, False, False, {"type": "run", "piece_id": piece}, "accepted", {"type": "ran"})


def finished(seq: int, outcome: str = "ran", failed: int = 0, overlaps: int = 0) -> Finished:
    if outcome != "ran":
        return Finished(seq, 2, 1, 0.0, 1.0, outcome, None, None, None, None, None)
    return Finished(seq, 2, 1, 0.0, 1.0, outcome, 0, 3, failed, overlaps, None)


def said(id: int, author: Any, at: float, answers: int | None = None, follows: bool = False, text: str = "x") -> Said:
    return Said(id, 1, author, at, follows, answers, text)


def verdict(asks_to_look: bool = False, asked_form: bool = False, claims_done: bool = False,
            asked_rows: tuple[str, ...] = ()) -> Verdict:
    return Verdict(asks_to_look=asks_to_look, asked_form=asked_form, claims_done=claims_done,
                   asked_rows=list(asked_rows), asked_other=0)


def record(looks: tuple[Look, ...] = (Look(20, 3, 510.0), Look(30, 2, 970.0)), before: str = BEFORE) -> Record:
    commands = (added(1, 0, "facts", before), added(2, 0, "model", "m"), added(3, 0, "image", "{}", True),
                edited(4, 200, 2, "m", "m2"), ran(5, 210), edited(6, 300, 1, before, AFTER), ran(7, 350),
                added(8, 480, "image", "{}", True), added(9, 950, "note", "n"), ran(10, 960))
    turns = (said(10, "person", 100), said(11, "ashley", 150, 10, follows=True), said(12, "ashley", 400, 10),
             said(20, "household", 500), said(21, "ashley", 520, 20), said(30, "person", 900), said(31, "ashley", 1000, 30))
    verdicts = {12: verdict(claims_done=True, asks_to_look=True, asked_rows=("b",)),
                21: verdict(asked_form=True, asked_rows=("b",)), 31: verdict(claims_done=True)}
    runs = {5: finished(5, overlaps=1), 7: finished(7, failed=2, overlaps=1), 10: finished(10, "failed")}
    return Record(turns, commands, looks, runs, verdicts)


EXPECTED: dict[int, dict[str, object]] = {
    10: {"build_s": 110.0, "model_runs": 2, "unasked_changes": 1, "unasked_by_kind": {"facts": 1},
         "measurement_rewrites": 2, "confirmed_rewrites": 1, "overlaps_final": 1, "failed_checks_final": 2,
         "looked_at_photo": False, "asks_to_look": True, "asked_form": False, "claimed_unbacked": True,
         "measurement_reasks": 0, "reask_basis": "grader"},
    20: {"build_s": None, "model_runs": 0, "unasked_changes": 0, "looked_at_photo": True, "asks_to_look": False,
         "asked_form": True, "claimed_unbacked": False, "measurement_reasks": 1},
    30: {"build_s": None, "model_runs": 1, "unasked_changes": 1, "unasked_by_kind": {"note": 1}, "overlaps_final": None,
         "failed_checks_final": None, "looked_at_photo": False, "claimed_unbacked": True, "measurement_reasks": 0},
}


def wrong(got: list[m.AskMeasures]) -> set[str]:
    """The fields that differ from `EXPECTED`."""
    by_turn = {a.turn_id: asdict(a) for a in got}
    return {f"{t}.{k}" for t, want in EXPECTED.items() for k, v in want.items() if by_turn[t][k] != v}


def test_each_ask_is_measured_as_its_contract_says() -> None:
    got = m.measure(record())
    assert [a.turn_id for a in got] == [10, 20, 30] and [a.author for a in got] == ["person", "household", "person"]
    assert wrong(got) == set()


def test_a_held_line_is_not_the_answer_graded() -> None:
    assert m.measure(replace(record(), verdicts={11: verdict(asks_to_look=True)}))[0].asks_to_look is None


def test_with_no_verdict_the_graded_measures_are_unknown_and_the_records_stand() -> None:
    first = m.measure(replace(record(), verdicts={}))[0]
    assert (first.asks_to_look, first.asked_form, first.claimed_unbacked, first.measurement_reasks) == (None,) * 4
    assert (first.build_s, first.model_runs) == (110.0, 2)


def test_rows_the_bench_surfaced_before_an_ask_decide_its_reask() -> None:
    shown = Command(11, 300.0, False, False, {"type": "surfaced", "piece_id": 1, "rows": [{"name": "b", "value": "10 mm"}]},
                    "accepted", {"type": "shown", "piece_id": 1, "rows": [{"name": "b", "value": "10 mm"}]})
    base = record()
    first, second = m.measure(replace(base, commands=(*base.commands, shown)))[:2]
    assert (first.reask_basis, first.measurement_reasks) == ("shown", 0)
    assert (second.reask_basis, second.measurement_reasks) == ("shown", 1)


def test_a_photo_look_or_a_form_question_before_the_first_model_change() -> None:
    assert m.form_before_model(record()) is False
    assert m.form_before_model(record(looks=(Look(10, 3, 150.0),))) is True
    early = replace(record(), turns=(*record().turns, said(13, "ashley", 160, 10)),
                    verdicts={13: verdict(asked_form=True)})
    assert m.form_before_model(early) is True
    assert m.form_before_model(replace(record(), commands=record().commands[:3])) is None


def _clean_any(run: Finished | None, checks: bool) -> bool:
    return run is not None


def _build_zero(self: m.Window) -> float | None:
    return 0.0


def _runs_all(self: m.Window) -> list[Command]:
    return self.mine


def _no_piece(c: Command) -> int:
    return -1


def _any_origin(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    return True


def _first_run(self: m.Window) -> Finished | None:
    runs = self.runs()
    return self.record.runs.get(runs[0].seq) if runs else None


def _any_look(r: Record, start: float, end: float, kinds: Mapping[int, str]) -> bool:
    return any(start <= x.at < end for x in r.looks)


def _no_look(r: Record, start: float, end: float, kinds: Mapping[int, str]) -> bool:
    return False


def _held_answer(self: m.Window) -> int | None:
    return next(t.id for t in self.record.turns if t.answers == self.ask.id)


MUTANTS: dict[str, tuple[str, object, str]] = {
    "clean run ignores the exit": ("_clean_run", _clean_any, "30.claimed_unbacked"),
    "a build counts any run": ("Window.build_s", _build_zero, "10.build_s"),
    "runs counts every change": ("Window.runs", _runs_all, "10.model_runs"),
    "scope ignores the piece": ("_piece_of", _no_piece, "10.unasked_changes"),
    "a new source still counts": ("_same_origin", _any_origin, "10.measurement_rewrites"),
    "confirmed counts guesses": ("GUESSED", "nothing", "10.confirmed_rewrites"),
    "the first run is the last": ("Window.last_run", _first_run, "10.failed_checks_final"),
    "any look is a photo": ("looked_at_photo", _any_look, "30.looked_at_photo"),
    "the held line is graded": ("Window.answer_id", property(_held_answer), "10.asks_to_look"),
}


def plant(monkeypatch: pytest.MonkeyPatch, where: str, value: object) -> None:
    owner, _, name = where.rpartition(".")
    monkeypatch.setattr(m.Window if owner else m, name, value)


class _Forgetful(m.Window):
    def shown_rows(self) -> set[str] | None:
        return set()


@pytest.mark.parametrize("name", list(MUTANTS))
def test_a_planted_wrong_measure_goes_red(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    where, value, field = MUTANTS[name]
    plant(monkeypatch, where, value)
    assert field in wrong(m.measure(record()))


def test_a_reask_goes_red_when_earlier_asks_are_forgotten(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m, "Window", _Forgetful)
    assert "20.measurement_reasks" in wrong(m.measure(record()))


def test_form_before_model_goes_red_when_photo_looks_are_not_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m, "looked_at_photo", _no_look)
    assert m.form_before_model(record(looks=(Look(10, 3, 150.0),))) is False

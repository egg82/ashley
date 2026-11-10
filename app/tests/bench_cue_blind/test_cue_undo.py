"""A cue and the undo walk: an Undo naming a cue is `nothing_to_undo`, `next_undo` and `Step(run=True)` pass over a cue
among real commands, and a cue is no later change that blocks undoing what came before it."""

from dataclasses import dataclass, field

from ashley.workshop.commands import Command, Cue, Edit, Move, Undo
from ashley.workshop.decide import EMPTY, Accepted, BenchState, Decision, decide
from ashley.workshop.model import Place, Text
from ashley.workshop.undo_walk import Step, next_undo
from bench_cue_blind_support import ALANA, HER, RULES, TUBE, accepted, add_note, add_video, cue, reason, undo


@dataclass
class Bench:
    """A bench driven through `decide` and `next_undo` alone; a cue is a `run` step, as the log reduces it."""

    state: BenchState = EMPTY
    log: list[Step] = field(default_factory=list[Step])

    def do(self, *commands: Command) -> Decision:
        got: Decision | None = None
        for command in commands:
            got = decide(self.state, command, RULES)
            self.log.append(Step(got.seq, isinstance(got, Accepted), command.seq if isinstance(command, Undo) else None,
                                 isinstance(command, Cue)))
            self.state = got.state
        assert got is not None
        return got

    def press(self) -> Decision:
        target = next_undo(self.log)
        assert target is not None
        return self.do(undo(target))


def test_next_undo_passes_over_a_run_step() -> None:
    assert next_undo([Step(1, True), Step(2, True, run=True)]) == 1
    assert next_undo([Step(1, True), Step(2, True, run=True), Step(3, True, run=True)]) == 1
    assert next_undo([Step(1, True, run=True)]) is None


def test_next_undo_passes_over_cues_between_real_commands() -> None:
    log = [Step(1, True), Step(2, True, run=True), Step(3, True), Step(4, True, run=True), Step(5, True, run=True)]
    assert next_undo(log) == 3


def test_an_undo_naming_a_cue_is_nothing_to_undo() -> None:
    bench = Bench()
    bench.do(add_video(), cue(1, "play"))
    assert reason(bench.do(undo(2))) == "nothing_to_undo"
    assert reason(bench.do(undo(2, HER))) == "nothing_to_undo"


def test_an_undo_naming_a_seek_cue_leaves_the_bench_as_it_was() -> None:
    bench = Bench()
    bench.do(add_video(), cue(1, "seek", 30))
    before = bench.state.pieces
    bench.do(undo(2))
    assert bench.state.pieces == before


def test_a_cue_after_a_change_does_not_block_undoing_it() -> None:
    bench = Bench()
    bench.do(add_video(), cue(1, "play"), cue(1, "seek", 5))
    assert isinstance(bench.do(undo(1)), Accepted)
    assert bench.state.pieces == ()


def test_pressing_undo_walks_real_commands_newest_first_with_cues_between() -> None:
    bench = Bench()
    bench.do(add_note(), add_video(), cue(2, "play"), Move(ALANA, 1, Place(1, "full")), cue(2, "pause"),
             cue(2, "seek", 12), Edit(HER, 2, 1, Text("w", TUBE)), cue(2, "play"))
    assert next_undo(bench.log) == 7
    accepted(bench.press())
    assert next_undo(bench.log) == 4
    accepted(bench.press())
    assert next_undo(bench.log) == 2
    accepted(bench.press())
    assert next_undo(bench.log) == 1
    accepted(bench.press())
    assert next_undo(bench.log) is None
    assert bench.state.pieces == ()


def test_a_refused_cue_is_no_target_either() -> None:
    bench = Bench()
    bench.do(add_note(), cue(1, "play"), cue(9, "play"))
    assert next_undo(bench.log) == 1

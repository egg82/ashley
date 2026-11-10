"""The undo walk from the contract alone: pressing Undo again names the newest accepted non-Undo command not yet
undone (`next_undo` over the log, served as `BenchDetail.undo_next`), so repeated presses take the bench back one
command at a time, newest first; an undo is allowed while every later command on the piece was taken back, a command
undone or changed since is refused `changed_since`, an Undo cannot be undone (`nothing_to_undo`), there is no redo, the
walk stops at a refusal rather than reaching past it, and anyone's command is undone by anyone."""

from collections.abc import Generator, Sequence
from dataclasses import dataclass, field

import pytest
from ashley.api.workshop_models import BenchDetail, BenchSummary
from ashley.workshop.commands import Add, Command, Edit, Move, Remove, Undo
from ashley.workshop.decide import EMPTY, Accepted, BenchState, Decision, Refused, decide
from ashley.workshop.model import SIZES, By, Piece, Place, Text
from ashley.workshop.undo_walk import Step, next_undo
from blind_support import ALANA, RULES, SAM, accepted, add, edit, move, reason, remove, shape, undo
from hypothesis import given, settings
from hypothesis import strategies as st
from respond_support import Fakes, wired as wired
from route_support import Rig, build


@dataclass
class Bench:
    """A bench driven only through `decide` and `next_undo`: the state and the log the walk reads."""

    state: BenchState = EMPTY
    log: list[Step] = field(default_factory=list[Step])

    def do(self, first: Command, *rest: Command) -> Decision:
        got = self.one(first)
        for command in rest:
            got = self.one(command)
        return got

    def one(self, command: Command) -> Decision:
        got = decide(self.state, command, RULES)
        self.log.append(Step(got.seq, isinstance(got, Accepted), command.seq if isinstance(command, Undo) else None))
        self.state = got.state
        return got

    def next(self) -> int | None:
        return next_undo(self.log)

    def press(self, by: By = ALANA) -> Decision:
        target = self.next()
        assert target is not None
        return self.do(undo(target, by))

    def shapes(self) -> list[tuple[int, str, Text, Place]]:
        return [shape(p) for p in self.state.pieces]


def shapes_of(pieces: Sequence[Piece]) -> list[tuple[int, str, Text, Place]]:
    return [shape(p) for p in pieces]


# --- next_undo on a hand-written log -----------------------------------------------------------------------------


def test_next_undo_of_an_empty_log_is_none() -> None:
    assert next_undo([]) is None


def test_next_undo_is_the_newest_accepted_command() -> None:
    assert next_undo([Step(1, True), Step(2, True), Step(3, True)]) == 3


def test_next_undo_accepts_any_iterable_of_steps() -> None:
    assert next_undo(iter([Step(1, True), Step(2, True)])) == 2


def test_next_undo_skips_refused_commands() -> None:
    assert next_undo([Step(1, True), Step(2, False), Step(3, False)]) == 1
    assert next_undo([Step(1, False)]) is None


def test_next_undo_never_names_an_undo() -> None:
    assert next_undo([Step(1, True), Step(2, True, undid=1)]) is None
    assert next_undo([Step(1, True), Step(2, True), Step(3, True, undid=2)]) == 1


def test_next_undo_ignores_a_refused_undo() -> None:
    assert next_undo([Step(1, True), Step(2, True), Step(3, False, undid=2)]) == 2


def test_next_undo_walks_past_each_command_an_accepted_undo_took_back() -> None:
    log = [Step(1, True), Step(2, True), Step(3, True), Step(4, True, undid=3), Step(5, True, undid=2)]
    assert next_undo(log) == 1
    assert next_undo([*log, Step(6, True, undid=1)]) is None


def test_next_undo_skips_a_command_undone_out_of_order() -> None:
    assert next_undo([Step(1, True), Step(2, True), Step(3, True, undid=2)]) == 1
    assert next_undo([Step(1, True), Step(2, True), Step(3, True, undid=1)]) == 2


def test_next_undo_skips_a_refused_command_between_accepted_ones() -> None:
    assert next_undo([Step(1, True), Step(2, False), Step(3, True, undid=1)]) is None


# --- directed walks through decide --------------------------------------------------------------------------------


def test_add_edit_edit_then_three_undos_walk_back_one_command_each() -> None:
    b = Bench()
    b.do(add("a"), edit(1, 1, "b", "1"), edit(1, 2, "c", "2"))
    after = [b.shapes()]
    assert b.next() == 3
    accepted(b.press())
    assert b.next() == 2
    after.append(b.shapes())
    accepted(b.press())
    assert b.next() == 1
    after.append(b.shapes())
    accepted(b.press())
    assert b.next() is None
    assert after[0][0][2] == Text("c", "2")
    assert after[1][0][2] == Text("b", "1")
    assert after[2][0][2] == Text("a", "")
    assert b.shapes() == []
    assert dict(b.state.undos) == {4: 3, 5: 2, 6: 1}


def test_undo_walks_across_pieces_newest_command_first() -> None:
    b = Bench()
    b.do(add("a"), add("b"), edit(1, 1, "c"), edit(2, 1, "d"))
    seen: list[tuple[int | None, list[tuple[int, str, Text, Place]]]] = []
    while (target := b.next()) is not None:
        accepted(b.press())
        seen.append((target, b.shapes()))
    assert [t for t, _ in seen] == [4, 3, 2, 1]
    assert [[(i, text.title) for i, _, text, _ in s] for _, s in seen] == [[(1, "c"), (2, "b")], [(1, "a"), (2, "b")],
                                                                          [(1, "a")], []]


def test_a_move_between_two_adds_is_walked_back_with_the_pieces_in_their_earlier_order() -> None:
    b = Bench()
    b.do(add("a"), add("b"), move(1, 1), add("c"))
    orders: list[list[int]] = []
    while b.next() is not None:
        accepted(b.press())
        orders.append([p.id for p in b.state.pieces])
    assert orders == [[2, 1], [1, 2], [1], []]


def test_undoing_a_remove_brings_the_piece_back_and_the_walk_goes_on() -> None:
    b = Bench()
    b.do(add("a"), add("b"), remove(1))
    accepted(b.press())
    assert [p.id for p in b.state.pieces] == [1, 2]
    assert b.next() == 2
    accepted(b.press())
    accepted(b.press())
    assert b.next() is None and b.shapes() == []


def test_the_person_and_she_undo_each_others_commands() -> None:
    mine, hers = ALANA, By(None)
    b = Bench()
    b.do(add("a", by=mine), edit(1, 1, "h", by=hers))
    got = accepted(b.press(by=mine))
    assert b.next() == 1 and b.state.pieces[0].text.title == "a"
    assert got.state.undos == {3: 2}
    accepted(b.press(by=hers))
    assert b.next() is None and b.state.pieces == ()


def test_another_person_undoes_the_first_persons_command_and_the_reverse() -> None:
    b = Bench()
    b.do(add("a", by=ALANA), edit(1, 1, "s", by=SAM))
    accepted(b.press(by=ALANA))
    accepted(b.press(by=SAM))
    assert b.next() is None and b.state.pieces == ()


def test_a_command_already_undone_is_refused_changed_since() -> None:
    b = Bench()
    b.do(add("a"), add("b"), undo(2))
    assert reason(b.do(undo(2))) == "changed_since"
    assert b.next() == 1


def test_an_undo_cannot_be_undone_and_no_redo_exists() -> None:
    b = Bench()
    b.do(add("a"), edit(1, 1, "b"), undo(2))
    assert reason(b.do(undo(3))) == "nothing_to_undo"
    assert b.next() == 1
    assert [p.text.title for p in b.state.pieces] == ["a"]


@pytest.mark.parametrize("seq", [0, 99])
def test_an_undo_of_a_seq_no_command_has_is_nothing_to_undo(seq: int) -> None:
    assert reason(Bench().do(undo(seq))) == "nothing_to_undo"


def test_an_earlier_command_is_refused_while_a_later_change_to_its_piece_stands() -> None:
    b = Bench()
    b.do(add("a"), edit(1, 1, "b"))
    assert reason(b.do(undo(1))) == "changed_since"
    accepted(b.do(undo(2)))
    accepted(b.do(undo(1)))
    assert b.state.pieces == ()


def test_a_later_command_on_another_piece_does_not_block_an_earlier_undo() -> None:
    b = Bench()
    b.do(add("a"), add("b"), edit(2, 1, "c"))
    accepted(b.do(undo(1)))
    assert [p.id for p in b.state.pieces] == [2]
    assert b.next() == 3


def test_undo_of_a_remove_is_changed_since_once_the_piece_was_touched_after_it_came_back() -> None:
    b = Bench()
    b.do(add("a"), remove(1), undo(2), edit(1, 1, "z"))
    assert reason(b.do(undo(2))) == "changed_since"
    assert reason(b.do(undo(1))) == "changed_since"
    assert b.next() == 4


def test_undo_of_an_add_after_a_remove_stands_refused_until_the_remove_is_undone() -> None:
    b = Bench()
    b.do(add("a"), remove(1))
    assert reason(b.do(undo(1))) == "changed_since"
    assert b.next() == 2
    accepted(b.press())
    accepted(b.press())
    assert b.next() is None and b.state.pieces == ()


def test_a_refused_command_does_not_move_the_walk() -> None:
    b = Bench()
    b.do(add("a"), edit(1, 1, "b"))
    before = b.next()
    assert isinstance(b.do(edit(1, 1, "c")), Refused)
    assert isinstance(b.do(undo(1)), Refused)
    assert b.next() == before == 2


def test_the_walk_stops_at_a_command_that_cannot_be_undone_and_never_reaches_past_it() -> None:
    """Undoing the remove of `a` out of order refills the bench, so the walk, arriving at the later remove of `c`, finds
    no room to bring `c` back: it is refused (`changed_since` per the contract, `full` per `decide`'s docstring) and the
    older commands are left alone."""
    b = Bench()
    b.do(add("a"), add("b"), add("c"), remove(1), add("d"), remove(3))
    accepted(b.do(undo(4)))
    assert b.next() == 6
    stuck = b.do(undo(6))
    assert reason(stuck) in ("changed_since", "full")
    assert b.next() == 6
    assert [p.id for p in b.state.pieces] == [1, 2, 5]
    assert dict(b.state.undos) == {7: 4}


def test_the_walk_after_a_refusal_names_the_same_command_again() -> None:
    b = Bench()
    b.do(add("a"), edit(1, 1, "b"), undo(2))
    again = b.do(undo(2))
    assert reason(again) == "changed_since"
    assert b.next() == 1


# --- property: the walk over any command log ---------------------------------------------------------------------

ACTORS = (ALANA, SAM, By(None))


def draw_command(data: st.DataObject, state: BenchState, undos: bool) -> Command:
    by = data.draw(st.sampled_from(ACTORS))
    ids = [p.id for p in state.pieces]
    pid = data.draw(st.sampled_from(ids) if ids and data.draw(st.integers(0, 9)) < 8 else st.integers(0, 9))
    op = data.draw(st.sampled_from(("add", "add", "remove", "move", "move", "edit", "edit", "edit") + (("undo",) if undos else ())))
    if op == "add":
        return Add(by, "note", Text(data.draw(st.sampled_from(("a", "b", "abc"))), ""), data.draw(st.sampled_from(SIZES)))
    if op == "remove":
        return Remove(by, pid)
    if op == "move":
        return Move(by, pid, Place(data.draw(st.integers(0, max(len(ids) - 1, 0))), data.draw(st.sampled_from(SIZES))))
    if op == "edit":
        piece = state.piece(pid)
        base = piece.version if piece else 1
        return Edit(by, pid, base, Text(data.draw(st.sampled_from(("a", "b", "abc", "abcde"))), data.draw(st.sampled_from(("", "x")))))
    seqs = sorted(state.effects) or [0]
    return Undo(by, data.draw(st.sampled_from(seqs)))


def build_log(data: st.DataObject, steps: int, undos: bool) -> tuple[Bench, list[list[tuple[int, str, Text, Place]]]]:
    """A bench after `steps` random commands, and the bench's shapes before each accepted non-Undo command."""
    b = Bench()
    before: list[list[tuple[int, str, Text, Place]]] = []
    for _ in range(steps):
        command = draw_command(data, b.state, undos)
        was = b.shapes()
        got = b.do(command)
        if isinstance(got, Accepted) and not isinstance(command, Undo):
            before.append(was)
    return b, before


def walk(b: Bench) -> tuple[list[int], Refused | None]:
    """Press Undo until the walk names nothing or an Undo is refused; the seqs undone, and the refusal if any."""
    taken: list[int] = []
    while (target := b.next()) is not None:
        got = b.do(undo(target))
        if isinstance(got, Refused):
            return taken, got
        assert b.state.undos[got.seq] == target
        taken.append(target)
    return taken, None


@settings(max_examples=60, deadline=None)
@given(st.data(), st.integers(1, 14))
def test_walking_a_log_of_only_ordinary_commands_undoes_each_accepted_one_in_reverse_and_reaches_the_empty_bench(
        data: st.DataObject, steps: int) -> None:
    """With no Undo in the log, repeated `undo_next` presses never refuse and take each accepted command back once,
    newest first; after the k-th press the pieces equal the bench before the k-th newest accepted command, and the
    last press leaves the empty bench the log began with."""
    b, before = build_log(data, steps, undos=False)
    accepted_seqs = [s.seq for s in b.log if s.accepted]
    want = list(reversed(before))
    taken: list[int] = []
    while (target := b.next()) is not None:
        accepted(b.do(undo(target)))
        taken.append(target)
        assert b.shapes() == want[len(taken) - 1]
    assert taken == list(reversed(accepted_seqs))
    assert b.shapes() == []


@settings(max_examples=60, deadline=None)
@given(st.data(), st.integers(1, 14))
def test_walking_any_log_ends_at_the_empty_bench_or_at_a_refusal_it_reports(data: st.DataObject, steps: int) -> None:
    """For any log (random Undos included, accepted or not), pressing `undo_next` until it is None either empties the
    bench, which is what it was before the first accepted non-Undo command, or stops at a refused Undo whose reason is
    `changed_since` (or `full`, when a removed piece cannot return). Every target is an accepted non-Undo command
    older than the one before it, named at most once; a refusal leaves `undo_next` naming the same command; and once the
    walk has ended, `undo_next` stays None for ever after no new ordinary command."""
    b, _ = build_log(data, steps, undos=True)
    ordinary = {s.seq for s in b.log if s.accepted and s.undid is None}
    taken, refusal = walk(b)
    assert len(set(taken)) == len(taken) and taken == sorted(taken, reverse=True)
    assert set(taken) <= ordinary
    if refusal is None:
        assert b.next() is None
        assert b.shapes() == []
    else:
        assert refusal.reason in ("changed_since", "full")
        stuck = b.next()
        assert stuck is not None and all(stuck < t for t in taken)
        assert stuck in ordinary and stuck not in b.state.undos.values()
        assert isinstance(b.do(undo(stuck)), Refused)
        assert b.next() == stuck


# --- the route ----------------------------------------------------------------------------------------------------


@pytest.fixture
def rig(db_url: str, wired: Fakes) -> Generator[Rig]:
    made = build(db_url, wired)
    with made.client:
        yield made


def detail(rig: Rig, bench_id: int) -> BenchDetail:
    got = rig.get(f"/api/benches/{bench_id}")
    assert got.status == 200
    return BenchDetail.model_validate(got.json)


def test_the_bench_read_serves_undo_next_as_the_walk_goes_back(rig: Rig) -> None:
    bench = BenchSummary.model_validate(rig.post("/api/benches", {"title": "b"}).json).id
    path = f"/api/benches/{bench}/commands"
    assert detail(rig, bench).undo_next is None
    rig.post(path, {"type": "add", "kind": "note", "title": "a", "body": "", "size": "small"})
    rig.post(path, {"type": "edit", "piece_id": 1, "base_version": 1, "title": "b", "body": ""})
    assert detail(rig, bench).undo_next == 2
    assert rig.post(path, {"type": "undo", "seq": 2}).status == 200
    assert detail(rig, bench).undo_next == 1
    assert rig.post(path, {"type": "undo", "seq": 1}).status == 200
    assert detail(rig, bench).undo_next is None
    assert detail(rig, bench).pieces == []


def test_a_refused_undo_leaves_undo_next_unchanged(rig: Rig) -> None:
    bench = BenchSummary.model_validate(rig.post("/api/benches", {"title": "b"}).json).id
    path = f"/api/benches/{bench}/commands"
    rig.post(path, {"type": "add", "kind": "note", "title": "a", "body": "", "size": "small"})
    rig.post(path, {"type": "edit", "piece_id": 1, "base_version": 1, "title": "b", "body": ""})
    assert rig.post(path, {"type": "undo", "seq": 1}).status == 409
    assert detail(rig, bench).undo_next == 2

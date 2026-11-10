"""Random command sequences with Archive, Restore and Undo through `decide`: after every step the layout holds orders
0 to n-1 and never more than `max_pieces`, no piece is on both the layout and the shelf, the shelf is most recently
archived first, a step of add, remove, move, archive or restore does what the contract says to a model of the bench,
a shelved piece takes nothing but a restore, an archive or restore changes no piece's text or version, undoing the
last accepted archive or restore takes the bench back, and replay from empty reproduces the bench."""

from dataclasses import dataclass, field

from ashley.workshop.commands import Add, Archive, Command, Edit, Move, Remove, Restore, Run, Undo
from ashley.workshop.decide import EMPTY, Accepted, BenchState, Decision, Refused, decide, replay
from ashley.workshop.model import SIZES, By, Place, Text
from hypothesis import given, settings
from hypothesis import strategies as st
from shelf_support import RULES, core, ids

ACTORS = (By(7), By(8), By(None))
OPS = ("add", "add", "add", "remove", "move", "move", "edit", "archive", "archive", "archive", "restore", "restore",
       "restore", "undo", "undo")


def draw_command(data: st.DataObject, state: BenchState) -> Command:
    """A command the next step could be, mostly aimed at a piece on the layout or the shelf."""
    by = data.draw(st.sampled_from(ACTORS))
    op = data.draw(st.sampled_from(OPS))
    known = ids(state.pieces) + ids(state.shelf)
    stray = data.draw(st.integers(0, 9)) == 0
    pid = data.draw(st.sampled_from(known)) if known and not stray else data.draw(st.integers(0, 12))
    if op == "add":
        return Add(by, "note", Text(data.draw(st.sampled_from(("a", "b", "abc"))), data.draw(st.sampled_from(("", "x")))),
                   data.draw(st.sampled_from(SIZES)))
    if op == "remove":
        return Remove(by, pid)
    if op == "move":
        return Move(by, pid, Place(data.draw(st.integers(0, max(len(state.pieces) - 1, 0))),
                                   data.draw(st.sampled_from(SIZES))))
    if op == "edit":
        piece = next((p for p in (*state.pieces, *state.shelf) if p.id == pid), None)
        return Edit(by, pid, piece.version if piece else 1, Text("e", data.draw(st.sampled_from(("", "y")))))
    if op == "archive":
        return Archive(by, pid)
    if op == "restore":
        return Restore(by, pid)
    seqs = sorted(state.effects)
    return Undo(by, data.draw(st.sampled_from(seqs)) if seqs and not stray else data.draw(st.integers(0, 40)))


def check_invariants(state: BenchState) -> None:
    layout, shelf = ids(state.pieces), ids(state.shelf)
    assert [p.place.order for p in state.pieces] == list(range(len(layout)))
    assert len(layout) <= RULES.max_pieces
    assert not set(layout) & set(shelf)
    assert len(set(layout)) == len(layout) and len(set(shelf)) == len(shelf)
    assert all(0 < i < state.next_seq for i in layout + shelf)


@dataclass
class Model:
    """The layout (id to size, in order) and the shelf (ids, newest first) as the contract says a step moves them."""

    layout: list[tuple[int, str]] = field(default_factory=list[tuple[int, str]])
    shelf: list[int] = field(default_factory=list[int])

    def of(self, state: BenchState) -> None:
        self.layout = [(p.id, p.place.size) for p in state.pieces]
        self.shelf = ids(state.shelf)


def expect_refusal(model: Model, command: Command) -> str | None:
    """The reason the contract fixes for `command` on the modelled bench, None where it does not (or accepts)."""
    on_layout = {i for i, _ in model.layout}
    if isinstance(command, Archive):
        return None if command.piece_id in on_layout else "no_such_piece"
    if isinstance(command, Restore):
        if command.piece_id not in model.shelf:
            return "no_such_piece"
        return "full" if len(model.layout) >= RULES.max_pieces else None
    if isinstance(command, (Remove, Edit, Move, Run)) and command.piece_id in model.shelf:
        return "no_such_piece"
    if isinstance(command, Add):
        return "full" if len(model.layout) >= RULES.max_pieces else None
    return None


def step_model(model: Model, command: Command, seq: int) -> None:
    if isinstance(command, Add):
        model.layout.append((seq, command.size))
    elif isinstance(command, Remove):
        model.layout = [(i, s) for i, s in model.layout if i != command.piece_id]
    elif isinstance(command, Move):
        rest = [(i, s) for i, s in model.layout if i != command.piece_id]
        rest.insert(command.place.order, (command.piece_id, command.place.size))
        model.layout = rest
    elif isinstance(command, Archive):
        gone = next(e for e in model.layout if e[0] == command.piece_id)
        model.layout.remove(gone)
        model.shelf.insert(0, command.piece_id)
    elif isinstance(command, Restore):
        model.shelf.remove(command.piece_id)


def check_step(before: BenchState, model: Model, command: Command, got: Decision) -> None:
    after = got.state
    check_invariants(after)
    fixed = expect_refusal(model, command)
    if fixed is not None:
        assert isinstance(got, Refused) and got.reason == fixed, (command, got)
    if isinstance(got, Refused):
        assert after.pieces == before.pieces and after.shelf == before.shelf
        return
    assert isinstance(got, Accepted)
    if isinstance(command, (Archive, Restore, Move, Remove, Add)):
        if isinstance(command, Restore):
            shelved = next(p for p in before.shelf if p.id == command.piece_id)
            step_model(model, command, got.seq)
            model.layout.append((command.piece_id, shelved.place.size))
        else:
            step_model(model, command, got.seq)
        assert [(p.id, p.place.size) for p in after.pieces] == model.layout
        assert ids(after.shelf) == model.shelf
    if isinstance(command, (Archive, Restore)):
        by_id = {p.id: p for p in (*before.pieces, *before.shelf)}
        moved = by_id[command.piece_id]
        now = next(p for p in (*after.pieces, *after.shelf) if p.id == command.piece_id)
        assert (now.text, now.version, now.kind, now.place.size) == (moved.text, moved.version, moved.kind,
                                                                     moved.place.size)
        for other in (*before.pieces, *before.shelf):
            if other.id != moved.id:
                same = next(p for p in (*after.pieces, *after.shelf) if p.id == other.id)
                assert (same.text, same.version, same.changed_by) == (other.text, other.version, other.changed_by)
    if isinstance(command, (Edit, Move, Remove, Run)):
        assert ids(after.shelf) == ids(before.shelf)
    if not isinstance(command, Undo) and not isinstance(command, (Archive, Restore)):
        assert [core(p) for p in after.shelf] == [core(p) for p in before.shelf]


@given(st.data())
@settings(max_examples=20, deadline=None)
def test_the_bench_holds_its_invariants_and_follows_the_contract_at_every_step(data: st.DataObject) -> None:
    state = EMPTY
    model = Model()
    commands: list[Command] = []
    for _ in range(data.draw(st.integers(1, 30))):
        command = draw_command(data, state)
        got = decide(state, command, RULES)
        commands.append(command)
        check_step(state, model, command, got)
        if isinstance(command, Undo) and isinstance(got, Accepted):
            model.of(got.state)
        state = got.state
    assert replay(commands, RULES)[-1].state == state


@given(st.data())
@settings(max_examples=20, deadline=None)
def test_undoing_the_last_accepted_archive_or_restore_takes_the_bench_back(data: st.DataObject) -> None:
    state = EMPTY
    for _ in range(data.draw(st.integers(1, 25))):
        command = draw_command(data, state)
        if isinstance(command, Undo):
            continue
        got = decide(state, command, RULES)
        if isinstance(command, (Archive, Restore)) and isinstance(got, Accepted):
            by = data.draw(st.sampled_from(ACTORS))
            undone = decide(got.state, Undo(by, got.seq), RULES)
            assert isinstance(undone, Accepted), (command, undone)
            check_invariants(undone.state)
            assert [core(p) for p in undone.state.pieces] == [core(p) for p in state.pieces]
            if isinstance(command, Archive):
                assert [core(p) for p in undone.state.shelf] == [core(p) for p in state.shelf]
            else:
                assert sorted(map(str, map(core, undone.state.shelf))) == sorted(map(str, map(core, state.shelf)))
                assert ids(undone.state.shelf)[0] == command.piece_id
            assert [p.place.order for p in undone.state.pieces] == [p.place.order for p in state.pieces]
        state = got.state


@given(st.data())
@settings(max_examples=20, deadline=None)
def test_a_piece_is_always_in_exactly_one_place_or_gone(data: st.DataObject) -> None:
    """Every id an accepted Add made is on the layout, on the shelf, or was removed (and only a Remove, or an Undo of
    an Add, takes a piece off the bench altogether)."""
    state = EMPTY
    added: set[int] = set()
    for _ in range(data.draw(st.integers(1, 30))):
        command = draw_command(data, state)
        got = decide(state, command, RULES)
        if isinstance(got, Accepted) and isinstance(command, Add):
            added.add(got.seq)
        if isinstance(got, Accepted) and isinstance(command, (Archive, Restore, Move, Edit)):
            assert set(ids(got.state.pieces)) | set(ids(got.state.shelf)) == set(ids(state.pieces)) | set(ids(state.shelf))
        here = ids(got.state.pieces) + ids(got.state.shelf)
        assert len(here) == len(set(here)) and set(here) <= added
        state = got.state

"""Random accepted-and-refused command sequences through `decide`: the bench's invariants after every step, a step
by step model of add/remove/move, the version and `changed_by` laws, replay from empty reproducing the same bench, and
the undo of the last command restoring the state before it, and repeated undos walking back through the commands.
There is no redo: an undo cannot be undone."""

from dataclasses import replace

from ashley.workshop.commands import Add, Command, Edit, Edited, Move, Remove, Undo, piece_of
from ashley.workshop.decide import EMPTY, Accepted, BenchState, Decision, Refused, decide, replay
from ashley.workshop.model import SIZES, By, Place, Text
from ashley.workshop.undo_walk import Step, next_undo
from blind_support import RULES, add, edit, fold, move, remove, shape
from hypothesis import given, settings
from hypothesis import strategies as st


ACTORS = (By(7), By(8), By(None))
OPS = ("add", "add", "remove", "remove", "move", "move", "move", "edit", "edit", "edit", "undo", "undo")


def mostly(data: st.DataObject, valid: tuple[str, ...], invalid: tuple[str, ...]) -> str:
    """One of `valid` nine times in ten, else one of `invalid`, so a run reaches both kinds of outcome."""
    return data.draw(st.sampled_from(valid) if data.draw(st.integers(0, 9)) < 9 else st.sampled_from(invalid))


def draw_command(data: st.DataObject, state: BenchState) -> Command:
    """A command the next step could be: mostly aimed at what is on the bench, sometimes at nothing in particular."""
    by = data.draw(st.sampled_from(ACTORS))
    op = data.draw(st.sampled_from(OPS))
    on_bench = [p.id for p in state.pieces]
    pid = data.draw(st.sampled_from(on_bench) if on_bench and data.draw(st.integers(0, 9)) < 8 else st.integers(0, 9))
    text = Text(mostly(data, ("a", "b", "abc", "abcde"), ("abcdef", "", "  ")),
                mostly(data, ("", "x", "x" * 10), ("x" * 11, "x" * 51)))
    if op == "add":
        return Add(by, mostly(data, ("note", "doc"), ("video",)), text, data.draw(st.sampled_from(SIZES)))
    if op == "remove":
        return Remove(by, pid)
    if op == "move":
        order = data.draw(st.integers(0, max(len(on_bench) - 1, 0)) if data.draw(st.integers(0, 9)) < 9
                          else st.integers(0, 4))
        return Move(by, pid, Place(order, data.draw(st.sampled_from(SIZES))))
    if op == "edit":
        piece = state.piece(pid)
        base = piece.version if piece and data.draw(st.integers(0, 9)) < 8 else data.draw(st.integers(0, 4))
        return Edit(by, pid, base, text)
    seqs = sorted(state.effects)
    return Undo(by, data.draw(st.sampled_from(seqs)) if seqs and data.draw(st.integers(0, 9)) < 8
                else data.draw(st.integers(0, 12)))


def run(data: st.DataObject, steps: int) -> tuple[list[Command], list[Decision]]:
    state = EMPTY
    commands: list[Command] = []
    decisions: list[Decision] = []
    for _ in range(steps):
        command = draw_command(data, state)
        decision = decide(state, command, RULES)
        commands.append(command)
        decisions.append(decision)
        state = decision.state
    return commands, decisions


def expected_ids(before: list[int], command: Command, seq: int) -> list[int] | None:
    """The ids in order after an add, remove or move that the bench accepted; None for any other command."""
    if isinstance(command, Add):
        return [*before, seq]
    if isinstance(command, Remove):
        return [i for i in before if i != command.piece_id]
    if isinstance(command, Move):
        rest = [i for i in before if i != command.piece_id]
        rest.insert(command.place.order, command.piece_id)
        return rest
    return None


def check_step(before: BenchState, command: Command, got: Decision, index: int) -> None:
    assert got.seq == index + 1 == before.next_seq and got.state.next_seq == index + 2
    if isinstance(got, Refused):
        assert got.state == replace(before, next_seq=before.next_seq + 1)
        return
    pieces = got.state.pieces
    assert [p.place.order for p in pieces] == list(range(len(pieces)))
    assert len({p.id for p in pieces}) == len(pieces) <= RULES.max_pieces
    assert all(p.version >= 1 and 1 <= len(p.text.title.strip()) and len(p.text.title) <= 5 for p in pieces)
    assert all(len(p.text.body) <= RULES.kinds[p.kind].max_chars for p in pieces)
    assert got.seq in got.state.effects and got.state.effects[got.seq] == got.effect
    for seq, effect in before.effects.items():
        assert got.state.effects[seq] == effect
    want = expected_ids([p.id for p in before.pieces], command, got.seq)
    assert want is None or want == [p.id for p in pieces]
    changed = piece_of(got.effect)
    moved = None if changed is None else got.state.piece(changed)
    assert moved is None or moved.changed_by == got.seq


def check_laws(decisions: list[Decision]) -> None:
    """A piece's version is 1 plus the text changes it had; `changed_by` is the last accepted change to that piece."""
    final = decisions[-1].state
    for piece in final.pieces:
        mine = [d for d in decisions if isinstance(d, Accepted) and piece_of(d.effect) == piece.id]
        assert piece.version == 1 + sum(isinstance(d.effect, Edited) for d in mine)
        assert piece.changed_by == mine[-1].seq


@settings(max_examples=60, deadline=None)
@given(st.data(), st.integers(1, 16))
def test_every_step_keeps_the_benchs_invariants_and_its_laws(data: st.DataObject, steps: int) -> None:
    commands, decisions = run(data, steps)
    before = EMPTY
    for i, (command, got) in enumerate(zip(commands, decisions, strict=True)):
        check_step(before, command, got, i)
        before = got.state
    check_laws(decisions)


@settings(max_examples=60, deadline=None)
@given(st.data(), st.integers(1, 16))
def test_replaying_the_commands_from_empty_reproduces_every_decision(data: st.DataObject, steps: int) -> None:
    commands, decisions = run(data, steps)
    assert replay(commands, RULES) == decisions
    k = data.draw(st.integers(1, steps))
    assert replay(commands[:k], RULES) == decisions[:k]


@settings(max_examples=25, deadline=None)
@given(st.data(), st.integers(1, 15))
def test_undoing_the_last_accepted_command_restores_the_bench_and_an_undo_cannot_be_undone(
        data: st.DataObject, steps: int) -> None:
    commands, decisions = run(data, steps)
    before = EMPTY
    for command, last in zip(commands, decisions, strict=True):
        if isinstance(last, Accepted) and not isinstance(command, Undo):
            undone = decide(last.state, Undo(command.by, last.seq), RULES)
            assert isinstance(undone, Accepted), f"undo of {command} was {undone}"
            assert [shape(p) for p in undone.state.pieces] == [shape(p) for p in before.pieces]
            again = decide(undone.state, Undo(command.by, undone.seq), RULES)
            assert isinstance(again, Refused) and again.reason == "nothing_to_undo"
        before = last.state


@settings(max_examples=25, deadline=None)
@given(st.data(), st.integers(1, 15))
def test_pressing_undo_repeatedly_takes_back_each_accepted_command_once_newest_first(
        data: st.DataObject, steps: int) -> None:
    commands, decisions = run(data, steps)
    log = [Step(d.seq, isinstance(d, Accepted), c.seq if isinstance(c, Undo) else None)
           for c, d in zip(commands, decisions, strict=True)]
    state, taken = decisions[-1].state, list[int]()
    while (target := next_undo(log)) is not None:
        outcome = decide(state, Undo(ACTORS[0], target), RULES)
        log.append(Step(outcome.seq, isinstance(outcome, Accepted), target))
        state = outcome.state
        if isinstance(outcome, Refused):
            assert outcome.reason == "changed_since"
            break
        taken.append(target)
    assert taken == sorted(set(taken), reverse=True)
    if next_undo(log) is None:
        assert [shape(p) for p in state.pieces] == []


def test_undo_of_each_kind_of_command_on_a_bench_with_neighbours() -> None:
    setup = [add("a"), add("b"), add("c")]
    for command in (remove(1), remove(2), remove(3), move(1, 2, "full"), move(3, 0), move(2, 1, "large"),
                    edit(2, 1, "z", "q"), move(2, 1)):
        decisions = fold([*setup, command])
        after = decisions[-1]
        assert isinstance(after, Accepted)
        undone = decide(after.state, Undo(command.by, after.seq), RULES)
        assert isinstance(undone, Accepted)
        assert [shape(p) for p in undone.state.pieces] == [shape(p) for p in decisions[-2].state.pieces]
        assert [shape(p) for p in undone.state.pieces] == [shape(p) for p in decisions[-2].state.pieces]

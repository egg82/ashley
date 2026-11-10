"""`decide` from its contract: each command's acceptance and each refusal in its stated order, undo and redo, and replay
of a random log from empty reproducing the bench and every outcome."""

from hypothesis import given, settings
from hypothesis import strategies as st

from ashley.workshop.commands import Add, Command, Edit, Move, Remove, Undo
from ashley.workshop.decide import EMPTY, Accepted, BenchState, Decision, Refused, decide, replay
from ashley.workshop.model import HER, SIZES, By, Place, Text
from ashley.workshop.rules import Kind, Rules

NOTE = Kind("note", "stored", "Note", 10)
RULES = Rules({"note": NOTE}, max_pieces=3, title_max_chars=5, recent_commands=10, undo_window=100)
ALANA = By(7)


def run(*commands: Command) -> list[Decision]:
    return replay(commands, RULES)


def last(*commands: Command) -> Decision:
    return run(*commands)[-1]


def add(title: str = "a", body: str = "", by: By = ALANA) -> Add:
    return Add(by, "note", Text(title, body), "small")


def pieces(decision: Decision) -> list[tuple[int, str, int, int]]:
    return [(p.id, p.text.title, p.version, p.place.order) for p in decision.state.pieces]


def test_an_add_goes_last_with_its_seq_as_id_and_version_one() -> None:
    got = last(add("a"), add("b"))
    assert isinstance(got, Accepted) and got.seq == 2
    assert pieces(got) == [(1, "a", 1, 0), (2, "b", 1, 1)]
    assert got.state.pieces[1].changed_by == 2


def test_add_refusals_in_their_stated_order() -> None:
    assert isinstance(r := last(Add(ALANA, "sketch", Text("", "x" * 11), "small")), Refused) and r.reason == "unknown_kind"
    assert isinstance(r := last(Add(ALANA, "note", Text(" ", "x" * 11), "small")), Refused) and r.reason == "bad_title"
    assert isinstance(r := last(Add(ALANA, "note", Text("toolong", ""), "small")), Refused) and r.reason == "bad_title"
    assert isinstance(r := last(add("a", "x" * 11)), Refused) and r.reason == "too_long"
    assert isinstance(r := last(add(), add(), add(), add()), Refused) and r.reason == "full"


def test_a_refusal_uses_up_a_seq_and_changes_nothing_else() -> None:
    first, refused, third = run(add(), Remove(ALANA, 9), add())
    assert isinstance(refused, Refused) and refused.reason == "no_such_piece"
    assert refused.state.pieces == first.state.pieces and refused.state.next_seq == 3
    assert [p.id for p in third.state.pieces] == [1, 3]


def test_a_move_shifts_the_others_and_past_the_end_is_bad_place() -> None:
    got = last(add("a"), add("b"), add("c"), Move(ALANA, 3, Place(0, "full")))
    assert pieces(got) == [(3, "c", 1, 0), (1, "a", 1, 1), (2, "b", 1, 2)]
    assert got.state.pieces[0].place.size == "full"
    assert isinstance(r := last(add(), Move(ALANA, 1, Place(1, "small"))), Refused) and r.reason == "bad_place"


def test_an_edit_on_a_stale_base_is_refused_and_a_current_one_raises_the_version() -> None:
    ok = last(add("a"), Edit(HER, 1, 1, Text("b", "x")))
    assert pieces(ok) == [(1, "b", 2, 0)]
    stale = last(add("a"), Edit(HER, 1, 1, Text("b", "")), Edit(ALANA, 1, 1, Text("c", "")))
    assert isinstance(stale, Refused) and stale.reason == "stale_base"


def test_undo_inverts_each_kind_of_change() -> None:
    assert pieces(last(add("a"), Remove(ALANA, 1), Undo(ALANA, 2))) == [(1, "a", 1, 0)]
    assert pieces(last(add("a"), Undo(ALANA, 1))) == []
    assert pieces(last(add("a"), Edit(ALANA, 1, 1, Text("b", "")), Undo(HER, 2))) == [(1, "a", 3, 0)]
    assert pieces(last(add("a"), add("b"), Move(ALANA, 2, Place(0, "full")), Undo(ALANA, 3))) == [
        (1, "a", 1, 0), (2, "b", 1, 1)]


def test_undo_refuses_what_changed_since_and_what_did_nothing() -> None:
    changed = last(add("a"), Edit(ALANA, 1, 1, Text("b", "")), Undo(ALANA, 1))
    assert isinstance(changed, Refused) and changed.reason == "changed_since"
    twice = last(add("a"), Remove(ALANA, 1), Undo(ALANA, 2), Undo(ALANA, 2))
    assert isinstance(twice, Refused) and twice.reason == "changed_since"
    for target in (2, 3, 0):
        got = last(add("a"), Remove(ALANA, 5), Undo(ALANA, target))
        assert isinstance(got, Refused) and got.reason == "nothing_to_undo"


ids = st.integers(min_value=0, max_value=8)
texts = st.builds(Text, st.sampled_from(["a", "bb", " ", "toolong"]), st.sampled_from(["", "x", "y" * 11]))
bys = st.sampled_from([ALANA, HER])
commands = st.one_of(
    st.builds(Add, bys, st.sampled_from(["note", "sketch"]), texts, st.sampled_from(SIZES)),
    st.builds(Remove, bys, ids),
    st.builds(Move, bys, ids, st.builds(Place, st.integers(0, 3), st.sampled_from(SIZES))),
    st.builds(Edit, bys, ids, st.integers(1, 3), texts),
    st.builds(Undo, bys, ids))


@settings(max_examples=60, deadline=None)
@given(st.lists(commands, max_size=12))
def test_replay_from_empty_reproduces_the_bench_and_every_outcome(log: list[Command]) -> None:
    decided = run(*log)
    state: BenchState = EMPTY
    for command, first in zip(log, decided, strict=True):
        again = decide(state, command, RULES)
        assert again == first
        state = again.state
        assert [p.place.order for p in state.pieces] == list(range(len(state.pieces)))
        assert len(state.pieces) <= RULES.max_pieces
    assert state.next_seq == len(log) + 1

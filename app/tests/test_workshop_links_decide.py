"""Links between pieces through `decide`: a Link and an Unlink accepted, each refusal in its stated order, a link that
changes neither end piece, undo both ways under the ordinary rules, a link kept while an end is off the layout and
shown again when it is back, and replay from empty reproducing the links and every outcome."""

from hypothesis import given, settings
from hypothesis import strategies as st

from ashley.workshop.codec import decode_command, decode_effect, encode_command, encode_effect
from ashley.workshop.commands import (Add, Archive, Command, Edit, Link, Linked, Remove, Restore, Undo, Unlink,
                                      Unlinked)
from ashley.workshop.decide import EMPTY, Accepted, BenchState, Decision, Refused, decide, replay
from ashley.workshop.links import PieceLink, visible
from ashley.workshop.model import HER, By, Text
from ashley.workshop.rules import Kind, Rules

NOTE = Kind("note", "stored", "Note", 10)
RULES = Rules({"note": NOTE}, max_pieces=4, title_max_chars=5, recent_commands=10, undo_window=100,
              link_kinds={"part_of": "Part of", "depends_on": "Depends on"})
ALANA = By(7)


def add(title: str = "a") -> Add:
    return Add(ALANA, "note", Text(title, ""), "small")


def last(*commands: Command) -> Decision:
    return replay(commands, RULES)[-1]


def refusal(*commands: Command) -> str:
    got = last(*commands)
    assert isinstance(got, Refused), got
    return got.reason


def shown(decision: Decision) -> tuple[PieceLink, ...]:
    return visible(decision.state.links, decision.state.pieces)


def test_a_link_is_accepted_and_changes_neither_piece() -> None:
    before = last(add("a"), add("b"))
    got = last(add("a"), add("b"), Link(HER, 2, "part_of", 1))
    assert isinstance(got, Accepted) and got.effect == Linked(PieceLink(2, "part_of", 1))
    assert got.state.pieces == before.state.pieces
    assert got.state.links == {PieceLink(2, "part_of", 1)}


def test_an_unlink_takes_the_link_away_and_changes_neither_piece() -> None:
    got = last(add("a"), add("b"), Link(HER, 2, "part_of", 1), Unlink(ALANA, 2, "part_of", 1))
    assert isinstance(got, Accepted) and got.effect == Unlinked(PieceLink(2, "part_of", 1))
    assert got.state.links == frozenset() and [p.changed_by for p in got.state.pieces] == [1, 2]


def test_two_kinds_between_the_same_pieces_and_each_direction_are_separate_links() -> None:
    got = last(add("a"), add("b"), Link(HER, 2, "part_of", 1), Link(HER, 2, "depends_on", 1), Link(HER, 1, "part_of", 2))
    assert isinstance(got, Accepted) and len(got.state.links) == 3


def test_link_refusals_in_their_stated_order() -> None:
    assert refusal(add(), Link(HER, 1, "part_of", 9)) == "no_such_piece"
    assert refusal(add(), Link(HER, 9, "nonsense", 1)) == "no_such_piece"
    assert refusal(add(), add(), Archive(ALANA, 2), Link(HER, 1, "part_of", 2)) == "no_such_piece"
    assert refusal(add(), add(), Remove(ALANA, 2), Link(HER, 2, "part_of", 1)) == "no_such_piece"
    assert refusal(add(), Link(HER, 1, "part_of", 1)) == "bad_link"
    assert refusal(add(), add(), Link(HER, 1, "nonsense", 2)) == "bad_link"
    assert refusal(add(), add(), Link(HER, 1, "part_of", 2), Link(ALANA, 1, "part_of", 2)) == "already_linked"


def test_unlink_refusals_in_their_stated_order() -> None:
    assert refusal(add(), Unlink(HER, 1, "part_of", 9)) == "no_such_piece"
    assert refusal(add(), add(), Link(HER, 1, "part_of", 2), Archive(ALANA, 2), Unlink(HER, 1, "part_of", 2)) == (
        "no_such_piece")
    assert refusal(add(), Unlink(HER, 1, "part_of", 1)) == "bad_link"
    assert refusal(add(), add(), Unlink(HER, 1, "nonsense", 2)) == "bad_link"
    assert refusal(add(), add(), Unlink(HER, 1, "part_of", 2)) == "not_linked"
    assert refusal(add(), add(), Link(HER, 1, "part_of", 2), Unlink(HER, 2, "part_of", 1)) == "not_linked"


def test_rules_with_no_link_kinds_take_no_link() -> None:
    bare = Rules({"note": NOTE}, max_pieces=4, title_max_chars=5, recent_commands=10, undo_window=100)
    got = replay([add(), add(), Link(HER, 1, "part_of", 2)], bare)[-1]
    assert isinstance(got, Refused) and got.reason == "bad_link"


def test_a_link_never_makes_an_edit_stale_nor_bumps_a_version() -> None:
    got = last(add("a"), add("b"), Link(HER, 2, "part_of", 1), Edit(ALANA, 1, 1, Text("c", "")))
    assert isinstance(got, Accepted) and got.state.piece(1) is not None and got.state.pieces[0].version == 2


def test_undo_of_a_link_unlinks_and_undo_of_an_unlink_links_again() -> None:
    undone = last(add(), add(), Link(HER, 2, "part_of", 1), Undo(ALANA, 3))
    assert isinstance(undone, Accepted) and undone.effect == Unlinked(PieceLink(2, "part_of", 1))
    assert undone.state.links == frozenset()
    back = last(add(), add(), Link(HER, 2, "part_of", 1), Unlink(ALANA, 2, "part_of", 1), Undo(HER, 4))
    assert isinstance(back, Accepted) and back.effect == Linked(PieceLink(2, "part_of", 1))


def test_undo_of_a_link_changed_since_is_refused_until_the_later_change_is_undone() -> None:
    log: list[Command] = [add(), add(), Link(HER, 2, "part_of", 1), Unlink(ALANA, 2, "part_of", 1)]
    assert refusal(*log, Undo(ALANA, 3)) == "changed_since"
    assert isinstance(last(*log, Undo(ALANA, 4), Undo(ALANA, 3)), Accepted)
    assert refusal(add(), add(), Link(HER, 2, "part_of", 1), Undo(ALANA, 3), Undo(ALANA, 3)) == "changed_since"
    assert refusal(add(), add(), Link(HER, 2, "part_of", 1), Undo(ALANA, 3), Undo(ALANA, 4)) == "nothing_to_undo"


def test_a_link_is_not_a_change_of_its_pieces_for_undo() -> None:
    edited = last(add(), add(), Edit(ALANA, 1, 1, Text("b", "")), Link(HER, 2, "part_of", 1), Undo(ALANA, 3))
    assert isinstance(edited, Accepted) and edited.state.pieces[0].text.title == "a"
    added = last(add(), add(), Link(HER, 2, "part_of", 1), Undo(ALANA, 2))
    assert isinstance(added, Accepted) and [p.id for p in added.state.pieces] == [1]
    assert added.state.links == {PieceLink(2, "part_of", 1)} and shown(added) == ()


def test_a_removed_end_hides_its_links_and_undoing_the_remove_brings_them_back() -> None:
    log: list[Command] = [add(), add(), add(), Link(HER, 2, "part_of", 1), Link(HER, 3, "depends_on", 2), Remove(ALANA, 2)]
    gone = last(*log)
    assert isinstance(gone, Accepted) and shown(gone) == () and len(gone.state.links) == 2
    back = last(*log, Undo(ALANA, 6))
    assert isinstance(back, Accepted)
    assert shown(back) == (PieceLink(2, "part_of", 1), PieceLink(3, "depends_on", 2))


def test_a_shelved_end_hides_its_links_and_restoring_it_shows_them() -> None:
    log: list[Command] = [add(), add(), Link(HER, 2, "part_of", 1), Archive(ALANA, 1)]
    assert shown(last(*log)) == ()
    assert shown(last(*log, Restore(ALANA, 1))) == (PieceLink(2, "part_of", 1),)
    assert shown(last(*log, Undo(ALANA, 4))) == (PieceLink(2, "part_of", 1),)


def test_undo_of_a_link_reaches_it_while_an_end_is_off_the_layout() -> None:
    log: list[Command] = [add(), add(), Link(HER, 2, "part_of", 1), Remove(ALANA, 2), Undo(ALANA, 3)]
    unlinked = last(*log)
    assert isinstance(unlinked, Accepted) and unlinked.state.links == frozenset()
    assert shown(last(*log, Undo(ALANA, 4))) == ()


def test_links_and_their_effects_read_back_from_their_json() -> None:
    for command in (Link(HER, 2, "part_of", 1), Unlink(By(7, turn=3), 2, "depends_on", 1)):
        assert decode_command(encode_command(command), By(command.by.person_id)) == command
    for effect in (Linked(PieceLink(2, "part_of", 1)), Unlinked(PieceLink(1, "depends_on", 3))):
        assert decode_effect(encode_effect(effect)) == effect
        assert "piece_id" not in encode_effect(effect)


ids = st.integers(min_value=1, max_value=6)
kinds = st.sampled_from(["part_of", "depends_on", "nonsense"])
commands = st.one_of(
    st.builds(Add, st.just(ALANA), st.just("note"), st.just(Text("a", "")), st.just("small")),
    st.builds(Remove, st.just(ALANA), ids),
    st.builds(Archive, st.just(ALANA), ids),
    st.builds(Restore, st.just(ALANA), ids),
    st.builds(Link, st.just(HER), ids, kinds, ids),
    st.builds(Unlink, st.just(ALANA), ids, kinds, ids),
    st.builds(Undo, st.just(HER), st.integers(0, 14)))


@settings(max_examples=80, deadline=None)
@given(st.lists(commands, max_size=14))
def test_replay_from_empty_reproduces_the_links_and_every_outcome(log: list[Command]) -> None:
    decided = replay(log, RULES)
    state: BenchState = EMPTY
    for command, first in zip(log, decided, strict=True):
        again = decide(state, command, RULES)
        assert again == first
        state = again.state
        on = {p.id for p in (*state.pieces, *state.shelf)}
        assert all(k.from_id != k.to_id for k in state.links)
        assert all(k.from_id < state.next_seq and k.to_id < state.next_seq for k in state.links)
        assert {k.from_id for k in visible(state.links, state.pieces)} <= on

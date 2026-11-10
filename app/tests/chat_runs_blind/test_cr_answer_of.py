"""`answer_of`: each person turn's id to the turn that answers it, the last of hers before the person's next turn."""

from ashley.api.chat_runs import answer_of
from cr_support import turn, turns
from hypothesis import given
from hypothesis import strategies as st


def test_no_turns_answer_nothing() -> None:
    assert answer_of([]) == {}


def test_her_answer_answers_the_person_turn_before_it() -> None:
    assert answer_of(turns("pa")) == {1: 2}


def test_a_person_turn_with_nothing_of_hers_after_it_has_no_answer() -> None:
    assert answer_of(turns("p")) == {}
    assert answer_of(turns("pap")) == {1: 2}


def test_a_held_line_is_not_the_answer_the_answer_after_it_is() -> None:
    assert answer_of(turns("pha")) == {1: 3}


def test_a_conversation_ending_on_a_held_line_has_no_answer_yet() -> None:
    assert answer_of(turns("ph")) == {}
    assert answer_of(turns("papph")) == {1: 2}


def test_the_last_of_hers_before_the_next_person_turn_answers() -> None:
    assert answer_of(turns("paap")) == {1: 3}
    assert answer_of(turns("phaap")) == {1: 4}


def test_each_person_turn_has_its_own_answer() -> None:
    assert answer_of(turns("papha")) == {1: 2, 3: 5}


def test_a_person_turn_with_a_person_turn_straight_after_has_no_answer() -> None:
    assert answer_of(turns("ppa")) == {2: 3}


def test_turns_of_hers_before_any_person_turn_answer_nothing() -> None:
    assert answer_of(turns("aapa")) == {3: 4}


def test_the_answer_is_found_by_the_mark_not_by_position_or_text() -> None:
    held = [turn(1, "p"), turn(2, "a", follows=True, answers=1), turn(3, "a", answers=1)]
    assert answer_of(held) == {1: 3}
    assert answer_of([turn(1, "p"), turn(2, "a", answers=1), turn(3, "a", follows=True, answers=1)]) == {1: 2}


@st.composite
def exchanges(draw: st.DrawFn) -> str:
    """Segments of a person turn, an optional held line, then answers; only the last may stop at a held line."""
    count = draw(st.integers(0, 5))
    out = ""
    for i in range(count):
        held = draw(st.booleans())
        answers = draw(st.integers(1 if held and i != count - 1 else 0, 3))
        out += "p" + ("h" if held else "") + "a" * answers
    return out


def reference(shape: str) -> dict[int, int]:
    found: dict[int, int] = {}
    asker = 0
    for i, c in enumerate(shape, 1):
        if c == "p":
            asker = i
        elif c == "a" and asker:
            found[asker] = i
    return found


@given(exchanges())
def test_the_mapping_matches_the_contract_on_any_conversation(shape: str) -> None:
    assert answer_of(turns(shape)) == reference(shape)

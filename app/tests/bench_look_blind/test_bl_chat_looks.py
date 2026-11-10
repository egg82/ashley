"""`chat_looks`: a look for the page with its picture link, and which of her turns shows which looks."""

from datetime import UTC, datetime

from ashley.api import chat_looks
from ashley.conversations.model import Turn
from ashley.files import config as files_config
from ashley.looks import links
from ashley.looks.looks import Look
from bench_look_blind_support import SHOT_BYTES, sha

LINK_TTL_S = files_config.load().link_ttl_s
KEY = b"k" * 40
AT = datetime(2026, 1, 1, tzinfo=UTC)
NOW = 1_800_000_000.0


def look(id: int, turn: int, piece: int | None = None) -> Look:
    return Look(id, 3, 1, turn, f"c{id}", 12, piece, sha(SHOT_BYTES), "image/jpeg", len(SHOT_BYTES), AT)


def person(id: int) -> Turn:
    return Turn(id, "person", 1, "q", AT)


def hers(id: int, answers: int | None, follows: bool = False) -> Turn:
    return Turn(id, "ashley", None, "a", AT, follows=follows, answers=answers)


def test_a_wire_look_carries_the_rows_fields() -> None:
    wired = chat_looks.wire(look(5, 1, piece=8), KEY, NOW)
    assert (wired.id, wired.bench_id, wired.piece_id, wired.media_type) == (5, 12, 8, "image/jpeg")


def test_a_look_of_the_whole_bench_has_no_piece() -> None:
    assert chat_looks.wire(look(5, 1), KEY, NOW).piece_id is None


def test_its_link_is_a_picture_link_for_the_households_bytes() -> None:
    wired = chat_looks.wire(look(5, 1), KEY, NOW)
    assert wired.url is not None and wired.expires_at is not None
    picture = links.check_picture(KEY, wired.url.rsplit("/", 1)[-1], NOW)
    assert picture == links.Picture(3, sha(SHOT_BYTES), "image/jpeg", wired.expires_at)
    assert wired.url.startswith("/api/looks/")


def test_the_link_ends_within_the_ttl_and_not_before_half_of_it() -> None:
    wired = chat_looks.wire(look(5, 1), KEY, NOW)
    assert wired.expires_at is not None
    assert NOW + LINK_TTL_S / 2 <= wired.expires_at <= NOW + LINK_TTL_S


def test_two_reads_within_a_window_hand_out_the_same_address() -> None:
    first = chat_looks.wire(look(5, 1), KEY, NOW)
    second = chat_looks.wire(look(5, 1), KEY, NOW + 1)
    assert first == second


def test_a_link_stops_working_when_it_ends() -> None:
    wired = chat_looks.wire(look(5, 1), KEY, NOW)
    assert wired.url is not None and wired.expires_at is not None
    token = wired.url.rsplit("/", 1)[-1]
    assert links.check_picture(KEY, token, wired.expires_at + 1) is None


def test_with_no_key_there_is_no_link() -> None:
    wired = chat_looks.wire(look(5, 1), b"", NOW)
    assert (wired.url, wired.expires_at) == (None, None)


def test_a_look_is_under_the_turn_of_hers_that_answers_its_question() -> None:
    shown = chat_looks.under_answers([person(1), hers(2, 1)], [look(10, 1)], KEY, NOW)
    assert list(shown) == [2] and [w.id for w in shown[2]] == [10]


def test_a_held_line_has_none_and_the_final_answer_has_them() -> None:
    shown = chat_looks.under_answers([person(1), hers(2, 1, follows=True), hers(3, 1)], [look(10, 1)], KEY, NOW)
    assert list(shown) == [3]


def test_a_look_with_no_answer_yet_is_under_none() -> None:
    assert chat_looks.under_answers([person(1), hers(2, 1, follows=True)], [look(10, 1)], KEY, NOW) == {}


def test_a_look_whose_turn_is_not_among_the_turns_is_under_none() -> None:
    assert chat_looks.under_answers([person(1), hers(2, 1)], [look(10, 77)], KEY, NOW) == {}


def test_looks_stay_in_the_order_she_took_them_and_split_by_question() -> None:
    turns = [person(1), hers(2, 1), person(3), hers(4, 3)]
    shown = chat_looks.under_answers(turns, [look(10, 1), look(11, 3), look(12, 1)], KEY, NOW)
    assert [w.id for w in shown[2]] == [10, 12] and [w.id for w in shown[4]] == [11]


def test_nothing_taken_is_nothing_shown() -> None:
    assert chat_looks.under_answers([person(1), hers(2, 1)], [], KEY, NOW) == {}


def test_looks_handed_in_any_order_are_shown_in_the_order_she_took_them() -> None:
    shown = chat_looks.under_answers([person(1), hers(2, 1)], [look(12, 1), look(10, 1), look(11, 1)], KEY, NOW)
    assert [w.id for w in shown[2]] == [10, 11, 12]

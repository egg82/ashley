"""Which of her turns shows a look, and the link its picture is reached by: under her final answer to the person turn
that asked, in the order taken, never under a held line, a link per look that serves exactly its picture to the
household, which no file or page link can stand in for."""

from datetime import UTC, datetime

from ashley.api.chat_looks import under_answers, wire
from ashley.files.links import window_end
from ashley.conversations.model import Turn
from ashley.looks import links
from ashley.looks.looks import Look

AT = datetime(2026, 11, 1, tzinfo=UTC)
KEY = b"k" * 32
SHA = "a" * 64


def person(id: int) -> Turn:
    return Turn(id, "person", 1, "q", AT)


def hers(id: int, answers: int | None, follows: bool = False) -> Turn:
    return Turn(id, "ashley", None, "a", AT, follows, answers=answers)


def look(id: int, turn: int, piece: int | None = 4, media: str = "image/jpeg") -> Look:
    return Look(id, 7, 1, turn, f"c{id}", 9, piece, SHA, media, 100, AT)


def test_looks_sit_under_the_answer_in_the_order_taken_and_a_held_line_has_none() -> None:
    turns = [person(1), hers(2, 1, follows=True), hers(3, 1), person(4), hers(5, 4)]
    shown = under_answers(turns, [look(9, 4), look(7, 1), look(8, 1, None)], KEY, now=1000)
    assert {k: [(x.id, x.piece_id) for x in v] for k, v in shown.items()} == {3: [(7, 4), (8, None)], 5: [(9, 4)]}


def test_a_look_whose_turn_has_no_answer_or_is_not_in_the_conversation_is_shown_nowhere() -> None:
    assert under_answers([person(1), hers(2, 1, follows=True)], [look(1, 1)], KEY, now=1000) == {}
    assert under_answers([person(1), hers(2, 1)], [look(1, 3)], KEY, now=1000) == {}


def test_its_link_serves_its_household_and_hash_and_ends_with_the_window() -> None:
    shown = wire(look(1, 1), KEY, now=1000)
    assert shown.url is not None and shown.url.startswith(links.PICTURE_PATH)
    picture = links.check_picture(KEY, shown.url[len(links.PICTURE_PATH):], now=1000)
    assert picture == links.Picture(7, SHA, "image/jpeg", shown.expires_at or 0)
    assert shown.expires_at == window_end(1000, 900)


def test_with_no_key_there_is_no_link() -> None:
    shown = wire(look(1, 1), b"", now=1000)
    assert shown.url is None and shown.expires_at is None and shown.media_type == "image/jpeg"


def test_a_picture_link_is_no_page_link_and_a_page_link_no_picture_link() -> None:
    token = links.mint_picture(KEY, links.Picture(7, SHA, "image/jpeg", 2000))
    assert links.check(KEY, token, now=0) is None
    page = links.mint(KEY, links.Grant(7, 1, 9, None, 2000))
    assert links.check_picture(KEY, page, now=0) is None
    assert links.check_picture(KEY, token, now=2000) is None

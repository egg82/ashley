"""The cheap model's pass as values: what is sent, and which of what comes back stands."""

import pytest

from ashley.inference.model import Message
from ashley.tidy import config as tidy_config
from ashley.tidy.config import TidyConfig
from ashley.tidy.pointer import Pointed, ask, check
from ashley.workshop.model import Piece, Place, Text
from tidy_support import CODE_STATUS, DECOMPILE, HEADER, STALE, found

CONFIG = tidy_config.load()


def piece(piece_id: int, kind: str, body: str, changed_by: int = 1, title: str = "t") -> Piece:
    return Piece(piece_id, kind, Text(title, body), 1, Place(piece_id, "medium"), changed_by)


def test_a_quote_in_the_piece_it_names_stands_and_an_invented_one_is_dropped() -> None:
    seen = {8: CODE_STATUS.body, 22: DECOMPILE.body}
    pointed = Pointed(findings=[found(8, "debris", HEADER), found(8, "superseded", "a sentence nobody wrote", 22),
                                found(22, "debris", STALE)])   # a real quote, but of piece 8, not 22
    got = check(pointed, seen, CONFIG)
    assert [(f.piece_id, f.kind, f.quote) for f in got.found] == [(8, "debris", HEADER)]
    assert got.dropped == 2


def test_a_quote_naming_a_piece_that_was_not_sent_is_dropped_and_an_unsent_other_piece_is_forgotten() -> None:
    seen = {8: CODE_STATUS.body}
    pointed = Pointed(findings=[found(9, "debris", HEADER), found(8, "superseded", STALE, by=22),
                                found(8, "duplicate", HEADER, by=8)])
    got = check(pointed, seen, CONFIG)
    assert [(f.quote, f.by_piece_id) for f in got.found] == [(STALE, None), (HEADER, None)]


def test_a_quote_outside_the_bounds_or_said_twice_is_dropped() -> None:
    seen = {8: CODE_STATUS.body}
    short, twice = CODE_STATUS.body[:CONFIG.min_quote_chars - 1], found(8, "debris", HEADER)
    long = CODE_STATUS.body[:CONFIG.max_quote_chars + 1]
    got = check(Pointed(findings=[found(8, "debris", short), found(8, "debris", long), twice, twice]), seen, CONFIG)
    assert [f.quote for f in got.found] == [HEADER]


def test_only_the_first_findings_up_to_the_cap_stand_and_a_reason_is_cut() -> None:
    config = CONFIG.model_copy(update={"max_findings": 2, "max_why_chars": 5})
    seen = {8: CODE_STATUS.body}
    quotes = [HEADER, STALE, CODE_STATUS.body[:40]]
    got = check(Pointed(findings=[found(8, "debris", q, why="a long reason") for q in quotes]), seen, config)
    assert [f.quote for f in got.found] == quotes[:2] and {f.why for f in got.found} == {"a lon"}
    assert got.per_kind() == {"debris": 2}


def test_the_prompt_carries_text_pieces_only_cut_to_the_bounds_and_the_cut_part_cannot_be_quoted() -> None:
    long = "x" * 50 + "\n" + "tail passage to quote"
    config = CONFIG.model_copy(update={"max_piece_chars": 40})
    asked = ask([piece(1, "site", "https://example.com/a"), piece(2, "reader", "page text"), piece(3, "note", long, title="N")],
                config)
    assert asked is not None and list(asked.seen) == [3] and len(asked.seen[3]) == 40
    message = asked.prompt.messages[0]
    assert isinstance(message, Message)
    text = message.text
    assert 'Piece 3 (note) "N"' in text and "example.com" not in text and "page text" not in text
    assert check(Pointed(findings=[found(3, "debris", "tail passage to quote")]), asked.seen, config).found == ()


def test_the_total_budget_keeps_the_pieces_changed_most_recently() -> None:
    config = CONFIG.model_copy(update={"max_total_chars": 25})
    asked = ask([piece(1, "note", "a" * 20, changed_by=3), piece(2, "note", "b" * 20, changed_by=9)], config)
    assert asked is not None and list(asked.seen) == [2]


def test_a_bench_with_no_text_piece_asks_nothing() -> None:
    assert ask([piece(1, "site", "https://example.com"), piece(2, "note", "  ")], CONFIG) is None


def test_the_shipped_config_loads_and_a_malformed_one_is_refused() -> None:
    data = {**CONFIG.model_dump(), "kinds": ["note"]}
    assert TidyConfig.model_validate(data).kinds == ("note",)
    for bad in ({**data, "kinds": []}, {**data, "shown": 0}, {**data, "extra": 1}, {**data, "min_quote_chars": 9, "max_quote_chars": 3}):
        with pytest.raises(ValueError):
            TidyConfig.model_validate(bad)

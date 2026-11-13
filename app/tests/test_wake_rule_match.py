"""A wake rule's optional `who` and `what`: parsed only in their shapes, matched exactly against the wake's own fields,
and of the rules answering one wake only the most specific runs, a tie at the top running none."""

import json
from datetime import UTC, datetime

import pytest
from ashley.channels.wake.rule import top
from ashley.senses.wakes import Wake
from ashley.workshop.wake_rule import WakeRule, rule_of

AT = datetime(2026, 11, 13, 18, 0, tzinfo=UTC)


def body(**changes: object) -> str:
    return json.dumps({"event": "arrived", "brief": "Greet them.", "tools": [], **changes})


def wake(who: str | None = "person.robin", what: str | None = None, event: str = "arrived") -> Wake:
    return Wake(1, "ctx-1", event, who, what, AT)


def rule(who: str | None = None, what: str | None = None, event: str = "arrived") -> WakeRule:
    return WakeRule(event, "Greet them.", (), who=who, what=what)


def picked(rules: list[WakeRule], w: Wake) -> list[int]:
    return [i for i, _ in top(list(enumerate(rules)), w)]


# ---- the shape


def test_a_rule_without_match_fields_reads_as_before_and_matches_any_who_and_what() -> None:
    old = rule_of(body())
    assert old is not None and old == WakeRule("arrived", "Greet them.", ()) and old.who is None and old.what is None
    assert old.specificity == 0
    assert old.answers("arrived", "person.robin", "front_door") and old.answers("arrived", None, None)
    assert not old.answers("left", "person.robin", None)


def test_who_and_what_are_read_back_as_written() -> None:
    got = rule_of(body(who="person.robin", what="front_door", greets=True))
    assert got is not None and got == WakeRule("arrived", "Greet them.", (), True, "person.robin", "front_door")
    assert got.specificity == 2
    assert rule_of(body(who="person.robin")) == WakeRule("arrived", "Greet them.", (), who="person.robin")
    assert rule_of(body(what="front_door")) == WakeRule("arrived", "Greet them.", (), what="front_door")


BAD = {"who null": body(who=None), "who empty": body(who=""), "who not a person entity": body(who="robin"),
       "who another domain": body(who="sensor.robin"), "who capitals": body(who="person.Robin"),
       "who words": body(who="person.robin when home"), "who a number": body(who=3), "who a list": body(who=["person.robin"]),
       "what null": body(what=None), "what empty": body(what=""), "what not a slug": body(what="Front Door"),
       "what an entity id": body(what="binary_sensor.door"), "what too long": body(what="a" * 65),
       "what a number": body(what=1), "what an object": body(what={"entity": "door"})}


@pytest.mark.parametrize("name", BAD)
def test_a_malformed_match_field_is_refused(name: str) -> None:
    assert rule_of(BAD[name]) is None


def test_the_refusals_have_a_well_formed_control() -> None:
    assert rule_of(body(who="person.robin_2", what="a" * 64)) is not None


# ---- matching


def test_a_who_rule_answers_only_that_persons_wake() -> None:
    mine = rule(who="person.robin")
    assert mine.answers("arrived", "person.robin", None) and mine.answers("arrived", "person.robin", "front_door")
    assert not mine.answers("arrived", "person.sam", None) and not mine.answers("arrived", None, None)
    assert not mine.answers("left", "person.robin", None)


def test_a_what_rule_answers_only_that_things_wake() -> None:
    door = rule(what="front_door")
    assert door.answers("arrived", None, "front_door") and door.answers("arrived", "person.sam", "front_door")
    assert not door.answers("arrived", "person.sam", "garage") and not door.answers("arrived", "person.sam", None)


# ---- the most specific wins


def test_bare_rules_alone_behave_as_before_one_answers_and_two_tie() -> None:
    assert picked([rule()], wake()) == [0]
    assert picked([rule(), rule()], wake()) == [0, 1]
    assert picked([rule(event="left")], wake()) == []


def test_a_who_rule_beats_the_bare_rule_for_that_person_and_not_for_another() -> None:
    rules = [rule(), rule(who="person.robin")]
    assert picked(rules, wake("person.robin")) == [1]
    assert picked(rules, wake("person.sam")) == [0]
    assert picked(rules, wake(None)) == [0]


def test_a_who_and_what_rule_beats_a_who_rule_and_the_bare_rule() -> None:
    rules = [rule(who="person.robin"), rule(), rule(who="person.robin", what="front_door")]
    assert picked(rules, wake("person.robin", "front_door")) == [2]
    assert picked(rules, wake("person.robin", "garage")) == [0]
    assert picked(rules, wake("person.sam", "front_door")) == [1]


def test_a_tie_at_the_top_stays_a_tie() -> None:
    assert picked([rule(who="person.robin"), rule(what="front_door"), rule()], wake("person.robin", "front_door")) == [0, 1]
    assert picked([rule(), rule(who="person.robin"), rule(who="person.robin")], wake("person.robin")) == [1, 2]


def test_a_rule_that_does_not_answer_never_outranks_one_that_does() -> None:
    rules = [rule(who="person.sam", what="front_door"), rule(event="left", who="person.robin"), rule()]
    assert picked(rules, wake("person.robin", "front_door")) == [2]

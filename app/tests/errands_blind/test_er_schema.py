"""The Null Object and the database's own constraints."""

from typing import Any

import psycopg
import pytest
from ashley import services
from ashley.errands.errands import Errands, ErrandsUnavailable
from errands_blind_support import World, count, insert_errand, new_conversation, new_turn, run, scenario


def test_unregistered_errands_is_a_null_that_raises_unavailable() -> None:
    errands = services.get(Errands)

    async def every_call() -> None:
        for call in (errands.owe(1, 1, 1, 1, "house"), errands.claim(frozenset({"house"}), 600),
                     errands.release(1, 1, 3), errands.finish(1, 1, "x"), errands.give_up(1, 1, "refused"),
                     errands.sweep(300, 600), errands.untold(1, 5), errands.told((1,))):
            with pytest.raises(ErrandsUnavailable):
                await call

    run(every_call())


def test_a_second_errand_for_one_turn_is_refused(db_url: str) -> None:
    async def body(w: World) -> None:
        turn = w.turn()
        insert_errand(w.url, household_id=w.hid, asker_id=w.asker, conversation_id=w.conv, turn_id=turn)
        with pytest.raises(psycopg.errors.UniqueViolation):
            insert_errand(w.url, household_id=w.hid, asker_id=w.asker, conversation_id=w.conv, turn_id=turn)
        assert count(w.url) == 1

    scenario(db_url, body)


def test_a_turn_of_another_household_is_refused(db_url: str) -> None:
    async def body(w: World) -> None:
        theirs = new_turn(w.url, w.other_hid, w.other_conv, w.other_person)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            insert_errand(w.url, household_id=w.hid, asker_id=w.asker, conversation_id=w.other_conv, turn_id=theirs)
        assert count(w.url) == 0

    scenario(db_url, body)


def test_a_turn_named_with_the_wrong_conversation_is_refused(db_url: str) -> None:
    async def body(w: World) -> None:
        other_conv = w.conv + 1000
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            insert_errand(w.url, household_id=w.hid, asker_id=w.asker, conversation_id=other_conv, turn_id=w.turn())

    scenario(db_url, body)


def test_an_asker_of_another_household_is_refused(db_url: str) -> None:
    async def body(w: World) -> None:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            insert_errand(w.url, household_id=w.hid, asker_id=w.other_person, conversation_id=w.conv, turn_id=w.turn())
        assert count(w.url) == 0

    scenario(db_url, body)


@pytest.mark.parametrize("column,value", [("state", "paused"), ("visibility", "members"), ("reason", "bored")])
def test_a_value_outside_the_closed_set_is_refused(db_url: str, column: str, value: str) -> None:
    async def body(w: World) -> None:
        kwargs: dict[str, str] = {column: value}
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_errand(w.url, household_id=w.hid, asker_id=w.asker, conversation_id=w.conv, turn_id=w.turn(),
                          state=kwargs.get("state", "given_up" if column == "reason" else "due"),
                          visibility=kwargs.get("visibility", "shared"), reason=kwargs.get("reason"))

    scenario(db_url, body)


@pytest.mark.parametrize("state,reason", [("given_up", "attempts"), ("given_up", "expired"),
                                          ("given_up", "interrupted"), ("given_up", "refused"), ("running", None),
                                          ("done", None), ("due", None)])
def test_every_listed_state_and_reason_is_accepted(db_url: str, state: str, reason: str | None) -> None:
    async def body(w: World) -> None:
        insert_errand(w.url, household_id=w.hid, asker_id=w.asker, conversation_id=w.conv, turn_id=w.turn(),
                      state=state, reason=reason, result="did it" if state == "done" else None)
        assert count(w.url) == 1

    scenario(db_url, body)


def test_a_turn_of_another_conversation_than_the_one_named_is_refused(db_url: str) -> None:
    async def body(w: World) -> None:
        elsewhere = new_conversation(w.url, w.hid, w.asker)
        turn = new_turn(w.url, w.hid, elsewhere, w.asker)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            insert_errand(w.url, household_id=w.hid, asker_id=w.asker, conversation_id=w.conv, turn_id=turn)
        assert count(w.url) == 0

    scenario(db_url, body)


@pytest.mark.parametrize("fields", [{"source": "   "}, {"source": ""}, {"attempts": -1},
                                    {"state": "given_up", "reason": None}, {"state": "due", "reason": "attempts"},
                                    {"state": "done", "result": None}, {"state": "due", "result": "did it"}])
def test_a_row_the_states_do_not_allow_is_refused(db_url: str, fields: dict[str, Any]) -> None:
    async def body(w: World) -> None:
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_errand(w.url, household_id=w.hid, asker_id=w.asker, conversation_id=w.conv, turn_id=w.turn(),
                          **fields)
        assert count(w.url) == 0

    scenario(db_url, body)


def test_an_errand_not_done_cannot_be_told(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = insert_errand(w.url, household_id=w.hid, asker_id=w.asker, conversation_id=w.conv, turn_id=w.turn())
        with psycopg.connect(w.url, autocommit=True) as conn, pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE errands SET told_at = now() WHERE id = %s", (eid,))

    scenario(db_url, body)


def test_an_errand_must_say_how_widely_it_was_heard(db_url: str) -> None:
    async def body(w: World) -> None:
        with psycopg.connect(w.url, autocommit=True) as conn, pytest.raises(psycopg.errors.NotNullViolation):
            conn.execute("INSERT INTO errands (household_id, asker_id, conversation_id, turn_id, source) "
                         "VALUES (%s, %s, %s, %s, 'house')", (w.hid, w.asker, w.conv, w.turn()))
        assert count(w.url) == 0

    scenario(db_url, body)

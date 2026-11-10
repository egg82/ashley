"""owe: one errand per person turn, stored due with the turn's visibility."""

from contract.conversations_support import gather_settled
from errands_blind_support import HOUSE, SEARCH, World, claim, count, row, scenario, seconds_since


def test_owe_stores_a_due_errand_with_its_fields(db_url: str) -> None:
    async def body(w: World) -> None:
        turn = w.turn()
        eid = await w.errands.owe(w.hid, w.asker, w.conv, turn, HOUSE)
        r = row(w.url, eid)
        assert r["state"] == "due"
        assert r["attempts"] == 0
        assert (r["household_id"], r["asker_id"], r["conversation_id"], r["turn_id"], r["source"]) == (
            w.hid, w.asker, w.conv, turn, HOUSE)
        assert r["result"] is None and r["reason"] is None
        assert r["claimed_at"] is None and r["finished_at"] is None and r["told_at"] is None
        assert 0 <= seconds_since(w.url, eid, "created_at") < 30

    scenario(db_url, body)


def test_owe_twice_for_one_turn_returns_the_same_id_and_stores_one(db_url: str) -> None:
    async def body(w: World) -> None:
        turn = w.turn()
        first = await w.errands.owe(w.hid, w.asker, w.conv, turn, HOUSE)
        again = await w.errands.owe(w.hid, w.asker, w.conv, turn, HOUSE)
        assert again == first
        assert count(w.url) == 1

    scenario(db_url, body)


def test_owe_again_for_a_turn_keeps_the_first_source(db_url: str) -> None:
    async def body(w: World) -> None:
        turn = w.turn()
        first = await w.errands.owe(w.hid, w.asker, w.conv, turn, HOUSE)
        again = await w.errands.owe(w.hid, w.asker, w.conv, turn, SEARCH)
        assert again == first
        assert row(w.url, first)["source"] == HOUSE

    scenario(db_url, body)


def test_owe_again_after_the_errand_ran_does_not_revive_it(db_url: str) -> None:
    async def body(w: World) -> None:
        turn = w.turn()
        eid = await w.errands.owe(w.hid, w.asker, w.conv, turn, HOUSE)
        assert await claim(w.errands, (HOUSE,)) == eid
        assert await w.errands.owe(w.hid, w.asker, w.conv, turn, HOUSE) == eid
        assert row(w.url, eid)["state"] == "running"
        assert count(w.url) == 1

    scenario(db_url, body)


def test_different_turns_owe_different_errands(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.owe()
        b = await w.owe()
        assert a != b
        assert count(w.url) == 2

    scenario(db_url, body)


def test_concurrent_owes_for_one_turn_make_one_errand(db_url: str) -> None:
    async def body(w: World) -> None:
        turn = w.turn()
        got = await gather_settled(*(w.errands.owe(w.hid, w.asker, w.conv, turn, HOUSE) for _ in range(6)))
        assert all(isinstance(g, int) for g in got), got
        assert len(set(got)) == 1
        assert count(w.url) == 1

    scenario(db_url, body)


def test_the_errand_keeps_the_turns_visibility(db_url: str) -> None:
    async def body(w: World) -> None:
        shared = await w.owe(visibility="shared")
        private = await w.owe(visibility="private")
        assert row(w.url, shared)["visibility"] == "shared"
        assert row(w.url, private)["visibility"] == "private"

    scenario(db_url, body)


def test_owe_for_a_turn_of_another_household_stores_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        # the turn is the home household's, named with the other household's id, person and conversation
        home_turn = w.turn()
        raised = False
        try:
            await w.errands.owe(w.other_hid, w.other_person, w.other_conv, home_turn, HOUSE)
        except Exception:
            raised = True
        assert raised
        assert count(w.url) == 0

    scenario(db_url, body)

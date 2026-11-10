"""The Looks record (`PostgresLooks` over the real database): one row per tool call, counted per turn, listed per
conversation, household-scoped; the Null Object keeps nothing."""

import asyncio

import pytest
from ashley.workshop.model import Owner
from ashley.looks.looks import LooksUnavailable, NullLooks
from bench_look_blind_support import SHOT_BYTES, go, new_look, scene, sha


def test_a_kept_look_is_listed_in_its_conversation_with_what_was_kept(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            conv, turn = await s.asked(s.w.alana)
            kept = await s.looks.keep(new_look(s.w.alana, conv, turn.id, "c1", bench=4, piece=8))
            (look,) = await s.looks.in_conversation(s.w.alana.household_id, conv)
            assert look.id == kept
            assert (look.household_id, look.conversation_id, look.turn_id, look.call_id) == (s.w.alana.household_id, conv, turn.id, "c1")
            assert (look.bench_id, look.piece_id, look.sha256, look.media_type, look.size) == (4, 8, sha(SHOT_BYTES), "image/jpeg", len(SHOT_BYTES))
            assert look.looked_at.tzinfo is not None

    go(scenario())


def test_a_look_of_the_whole_bench_has_no_piece(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            conv, turn = await s.asked(s.w.alana)
            await s.looks.keep(new_look(s.w.alana, conv, turn.id, "c1", piece=None))
            (look,) = await s.looks.in_conversation(s.w.alana.household_id, conv)
            assert look.piece_id is None

    go(scenario())


def test_a_second_keep_for_the_same_call_replaces_the_first(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            conv, turn = await s.asked(s.w.alana)
            await s.looks.keep(new_look(s.w.alana, conv, turn.id, "c1", data=b"first", media_type="image/png"))
            await s.looks.keep(new_look(s.w.alana, conv, turn.id, "c1", data=b"second-bytes", media_type="image/jpeg"))
            (look,) = await s.looks.in_conversation(s.w.alana.household_id, conv)
            assert (look.sha256, look.size, look.media_type) == (sha(b"second-bytes"), len(b"second-bytes"), "image/jpeg")

    go(scenario())


def test_a_resumed_call_does_not_count_against_the_turn(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            conv, turn = await s.asked(s.w.alana)
            await s.looks.keep(new_look(s.w.alana, conv, turn.id, "c1"))
            await s.looks.keep(new_look(s.w.alana, conv, turn.id, "c1"))
            assert await s.looks.taken(s.w.alana.household_id, turn.id, "other") == 1

    go(scenario())


def test_calls_of_one_turn_each_keep_a_look(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            conv, turn = await s.asked(s.w.alana)
            for c in ("a", "b", "c"):
                await s.looks.keep(new_look(s.w.alana, conv, turn.id, c))
            assert len(await s.looks.in_conversation(s.w.alana.household_id, conv)) == 3

    go(scenario())


def test_taken_counts_a_turns_looks_except_the_named_call(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            conv, turn = await s.asked(s.w.alana)
            assert await s.looks.taken(s.w.alana.household_id, turn.id, "a") == 0
            for c in ("a", "b", "c"):
                await s.looks.keep(new_look(s.w.alana, conv, turn.id, c))
            hid = s.w.alana.household_id
            assert await s.looks.taken(hid, turn.id, "a") == 2
            assert await s.looks.taken(hid, turn.id, "zzz") == 3

    go(scenario())


def test_taken_is_per_turn(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            conv, one = await s.asked(s.w.alana)
            await s.answer(conv, one)
            _, two = await s.asked(s.w.alana, "again")
            await s.looks.keep(new_look(s.w.alana, conv, one.id, "a"))
            await s.looks.keep(new_look(s.w.alana, conv, two.id, "a"))
            await s.looks.keep(new_look(s.w.alana, conv, two.id, "b"))
            hid = s.w.alana.household_id
            assert await s.looks.taken(hid, one.id, "x") == 1
            assert await s.looks.taken(hid, two.id, "x") == 2

    go(scenario())


def test_the_same_call_id_in_two_turns_is_two_looks(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            conv, one = await s.asked(s.w.alana)
            _, two = await s.asked(s.w.alana, "again")
            await s.looks.keep(new_look(s.w.alana, conv, one.id, "same"))
            await s.looks.keep(new_look(s.w.alana, conv, two.id, "same"))
            assert len(await s.looks.in_conversation(s.w.alana.household_id, conv)) == 2

    go(scenario())


def test_looks_come_oldest_first_by_id(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            conv, turn = await s.asked(s.w.alana)
            ids = [await s.looks.keep(new_look(s.w.alana, conv, turn.id, c)) for c in ("z", "m", "a")]
            got = await s.looks.in_conversation(s.w.alana.household_id, conv)
            assert [look.id for look in got] == sorted(ids) == ids

    go(scenario())


def test_a_conversation_with_no_looks_lists_none(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            conv, _ = await s.asked(s.w.alana)
            assert await s.looks.in_conversation(s.w.alana.household_id, conv) == []
            assert await s.looks.in_conversation(s.w.alana.household_id, 99_999) == []

    go(scenario())


def test_looks_are_listed_per_conversation(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            c1, t1 = await s.asked(s.w.alana)
            c2, t2 = await s.asked(s.w.sam)
            await s.looks.keep(new_look(s.w.alana, c1, t1.id, "a"))
            await s.looks.keep(new_look(s.w.sam, c2, t2.id, "b"))
            hid = s.w.alana.household_id
            assert [look.call_id for look in await s.looks.in_conversation(hid, c1)] == ["a"]
            assert [look.call_id for look in await s.looks.in_conversation(hid, c2)] == ["b"]

    go(scenario())


def test_another_household_sees_none_of_a_conversations_looks(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            conv, turn = await s.asked(s.w.alana)
            await s.looks.keep(new_look(s.w.alana, conv, turn.id, "a"))
            assert await s.looks.in_conversation(s.w.zed.household_id, conv) == []

    go(scenario())


def test_another_household_counts_none_of_a_turns_looks(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            conv, turn = await s.asked(s.w.alana)
            await s.looks.keep(new_look(s.w.alana, conv, turn.id, "a"))
            assert await s.looks.taken(s.w.zed.household_id, turn.id, "x") == 0

    go(scenario())


def test_one_households_keep_never_replaces_anothers(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            c1, t1 = await s.asked(s.w.alana)
            c2, t2 = await s.asked(s.w.zed)
            await s.looks.keep(new_look(s.w.alana, c1, t1.id, "same", data=b"alana"))
            await s.looks.keep(new_look(s.w.zed, c2, t2.id, "same", data=b"zed"))
            (mine,) = await s.looks.in_conversation(s.w.alana.household_id, c1)
            (theirs,) = await s.looks.in_conversation(s.w.zed.household_id, c2)
            assert (mine.sha256, theirs.sha256) == (sha(b"alana"), sha(b"zed"))

    go(scenario())


def test_the_null_looks_keeps_nothing() -> None:
    async def scenario() -> None:
        null = NullLooks()
        with pytest.raises(LooksUnavailable):
            await null.taken(1, 1, "x")
        with pytest.raises(LooksUnavailable):
            await null.keep(new_look(Owner(1, 1), 1, 1))

    go(scenario())


def test_a_replaced_look_is_dated_again(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            conv, turn = await s.asked(s.w.alana)
            await s.looks.keep(new_look(s.w.alana, conv, turn.id, "c1"))
            (first,) = await s.looks.in_conversation(s.w.alana.household_id, conv)
            await asyncio.sleep(0.05)
            await s.looks.keep(new_look(s.w.alana, conv, turn.id, "c1", data=b"again"))
            (second,) = await s.looks.in_conversation(s.w.alana.household_id, conv)
            assert second.looked_at > first.looked_at

    go(scenario())


def test_a_replacing_keep_replaces_the_piece_and_the_bench_too(db_url: str) -> None:
    async def scenario() -> None:
        async with scene(db_url) as s:
            conv, turn = await s.asked(s.w.alana)
            await s.looks.keep(new_look(s.w.alana, conv, turn.id, "c1", bench=4, piece=8))
            await s.looks.keep(new_look(s.w.alana, conv, turn.id, "c1", bench=5, piece=None))
            (look,) = await s.looks.in_conversation(s.w.alana.household_id, conv)
            assert (look.bench_id, look.piece_id) == (5, None)
            await s.looks.keep(new_look(s.w.alana, conv, turn.id, "c1", bench=5, piece=9))
            (look,) = await s.looks.in_conversation(s.w.alana.household_id, conv)
            assert look.piece_id == 9

    go(scenario())

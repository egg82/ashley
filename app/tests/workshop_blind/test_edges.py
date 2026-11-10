"""Edges of the contract the plain cases skip: numbers outside any database integer, characters that are or are not
whitespace, a bench whose rules shrank under it, racing closes, and the odd texts a person pastes."""

import asyncio
from types import MappingProxyType

import pytest
from ashley.db.database import Database
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import Rules
from ashley.workshop.workshop import Applied, BenchClosed, BenchNotFound, Workshop, WorkshopUnavailable
from blind_support import DOC, NOTE, RULES, add, edit, move, remove, undo
from contract.conversations_support import run
from service_support import workshop, world

HUGE = 2 ** 70
SPACES = (" ", "　", "  ", "\x0b\x0c", "  　")


def test_numbers_beyond_any_database_integer_are_refused_by_decide_not_crashed_on(db_url: str) -> None:
    w = world(db_url)
    me = By(w.alana.person_id)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench = await s.open(w.alana, "t")
            await s.apply(w.alana, bench.id, add("a", by=me))
            got = [await s.apply(w.alana, bench.id, c) for c in (
                remove(HUGE, me), remove(-HUGE, me), move(HUGE, 0, by=me), edit(HUGE, 1, by=me), edit(1, HUGE, by=me),
                edit(1, -HUGE, by=me), undo(HUGE, me), undo(-HUGE, me), move(1, HUGE, by=me))]
            assert [a.outcome for a in got] == ["no_such_piece"] * 4 + ["stale_base"] * 2 + ["nothing_to_undo"] * 2 + [
                "bad_place"]
            assert [a.seq for a in got] == list(range(2, 11))
            assert [row.command for row in (await s.log(w.alana, bench.id))[1:]] == [
                remove(HUGE, me), remove(-HUGE, me), move(HUGE, 0, by=me), edit(HUGE, 1, by=me), edit(1, HUGE, by=me),
                edit(1, -HUGE, by=me), undo(HUGE, me), undo(-HUGE, me), move(1, HUGE, by=me)]

    run(scenario())


def test_a_bench_id_beyond_any_database_integer_is_just_not_found(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            for bench_id in (HUGE, -HUGE, 2 ** 63, 2 ** 31):
                for call in (s.read(w.alana, bench_id), s.log(w.alana, bench_id), s.close(w.alana, bench_id),
                             s.apply(w.alana, bench_id, add("a", by=By(w.alana.person_id)))):
                    with pytest.raises(BenchNotFound):
                        await call

    run(scenario())


@pytest.mark.parametrize("space", SPACES)
def test_unicode_whitespace_is_whitespace_in_a_title(db_url: str, space: str) -> None:
    w = world(db_url)
    me = By(w.alana.person_id)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            with pytest.raises(ValueError):
                await s.open(w.alana, space)
            bench = await s.open(w.alana, "t")
            assert (await s.apply(w.alana, bench.id, add(space, by=me))).outcome == "bad_title"

    run(scenario())


def test_a_title_is_counted_in_characters_not_bytes_or_utf16_units(db_url: str) -> None:
    w = world(db_url)
    me = By(w.alana.person_id)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            for title in ("😀" * 6, "é" * 6, "é" * 3):       # 6 code points each
                with pytest.raises(ValueError):
                    await s.open(w.alana, title)
            bench = await s.open(w.alana, "😀" * 5)
            assert (await s.apply(w.alana, bench.id, add("😀" * 6, by=me))).outcome == "bad_title"
            assert (await s.apply(w.alana, bench.id, add("😀" * 5, "😀" * 10, by=me))).outcome == "accepted"
            assert (await s.apply(w.alana, bench.id, add("a", "😀" * 11, by=me))).outcome == "too_long"
            assert (await s.read(w.alana, bench.id)).pieces[0].text == Text("😀" * 5, "😀" * 10)

    run(scenario())


def test_a_bench_whose_rules_shrank_under_it_refuses_what_the_new_rules_do(db_url: str) -> None:
    w = world(db_url)
    me = By(w.alana.person_id)
    narrow = Rules(MappingProxyType({"doc": DOC}), max_pieces=2, title_max_chars=5, recent_commands=4, undo_window=100)
    assert NOTE.name == "note" and RULES.max_pieces == 3

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench = await s.open(w.alana, "t")
            for i in range(3):
                await s.apply(w.alana, bench.id, add(str(i), by=me))
        async with workshop(db_url, narrow) as s:
            assert (await s.apply(w.alana, bench.id, add("x", kind="doc", by=me))).outcome == "full"
            assert (await s.apply(w.alana, bench.id, edit(1, 1, "z", by=me))).outcome == "unknown_kind"
            assert (await s.apply(w.alana, bench.id, remove(1, me))).outcome == "accepted"
            assert (await s.apply(w.alana, bench.id, undo(6, me))).outcome == "full"       # 2 left, 2 allowed
            assert [p.id for p in (await s.read(w.alana, bench.id)).pieces] == [2, 3]

    run(scenario())


def test_an_owner_in_the_wrong_household_is_not_the_owner(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench = await s.open(w.alana, "t")
            wrong = Owner(w.zed.household_id, w.alana.person_id)
            for call in (s.read(wrong, bench.id), s.log(wrong, bench.id), s.close(wrong, bench.id),
                         s.apply(wrong, bench.id, add("a", by=By(w.alana.person_id)))):
                with pytest.raises(BenchNotFound):
                    await call
            assert await s.open_benches(wrong) == []

    run(scenario())


def test_racing_closes_all_answer_the_same_closed_bench(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench = await s.open(w.alana, "t")
            got = await asyncio.gather(*(s.close(w.alana, bench.id) for _ in range(5)))
            assert len({b.closed_at for b in got}) == 1 and got[0].closed_at is not None
            assert (await s.read(w.alana, bench.id)).bench == got[0]

    run(scenario())


def test_commands_racing_a_close_are_either_logged_before_it_or_closed_out(db_url: str) -> None:
    w = world(db_url)
    me = By(w.alana.person_id)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench = await s.open(w.alana, "t")
            calls = [s.apply(w.alana, bench.id, add(str(i), by=me)) for i in range(4)]
            got = await asyncio.gather(*calls, s.close(w.alana, bench.id), return_exceptions=True)
            decided = [g for g in got if isinstance(g, Applied)]
            assert all(isinstance(g, BenchClosed) for g in got if isinstance(g, BaseException))
            log = await s.log(w.alana, bench.id)
            assert sorted(a.seq for a in decided) == [row.seq for row in log] == list(range(1, len(decided) + 1))

    run(scenario())


@pytest.mark.parametrize("text", ["\ud7ff\ue000\U0010ffff", "line\r\nbreak", "\u202e\u200b", "'; DROP TABLE benches; --",
                                   '{"a": [1, 2', "%s %(x)s {0}"])
def test_a_body_is_whatever_text_a_person_pastes_and_comes_back_whole(db_url: str, text: str) -> None:
    w = world(db_url)
    me = By(w.alana.person_id)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench = await s.open(w.alana, "t")
            assert (await s.apply(w.alana, bench.id, add("a", text, "doc", by=me))).outcome == "accepted"
            assert (await s.read(w.alana, bench.id)).pieces[0].text.body == text
            assert (await s.log(w.alana, bench.id))[0].command == add("a", text, "doc", by=me)

    run(scenario())


def test_a_nul_in_a_command_is_a_value_error_and_logs_nothing(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench = await s.open(w.alana, "t")
            with pytest.raises(ValueError):
                await s.apply(w.alana, bench.id, add("a", "a\u0000b", "doc", by=By(w.alana.person_id)))
            assert await s.log(w.alana, bench.id) == []

    run(scenario())


# --- unavailable ----------------------------------------------------------------------------------------------


def test_with_no_database_every_call_is_unavailable_and_nothing_is_published() -> None:
    w, owner = PostgresWorkshop(Database.null(), RULES), Owner(1, 1)

    async def scenario() -> None:
        calls = (w.open(owner, "abc"), w.open_benches(owner), w.close(owner, 1), w.read(owner, 1),
                 w.apply(owner, 1, add("a", by=By(1))), w.log(owner, 1))
        for call in calls:
            with pytest.raises(WorkshopUnavailable):
                await call

    run(scenario())


def test_the_null_workshop_is_unavailable_for_every_call() -> None:
    null, owner = Workshop.null(), Owner(1, 1)

    async def scenario() -> None:
        for call in (null.open(owner, "abc"), null.open_benches(owner), null.close(owner, 1), null.read(owner, 1),
                     null.apply(owner, 1, add("a", by=By(1))), null.log(owner, 1)):
            with pytest.raises(WorkshopUnavailable):
                await call

    run(scenario())

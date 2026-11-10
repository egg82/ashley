"""What `apply` does with `standing` and the `diet` kind, the `memory.profile` log line and `NullMemory.profile`.
Written blind from the contract."""

import pytest
from ashley import logs
from ashley.memory.memory import Memory, MemoryUnavailable
from ashley.memory.model import Add, Kind, Update, Visibility
from ashley.memory.postgres import PostgresMemory

from conversations_support import events, run
from memory_support import pool
from profile_support import AT, LATER, add_all, asker, seated, column, new

OTHER_KINDS: list[Kind] = ["preference", "routine", "plan", "person", "home", "other"]


@pytest.mark.parametrize("said", [True, False])
@pytest.mark.parametrize(("visibility", "stated"), [("shared", False), ("shared", True), ("discreet", False),
                                                    ("private", True), ("private", False)])
def test_a_diet_is_always_standing_and_keeps_the_visibility_it_was_given(
        db_url: str, said: bool, visibility: Visibility, stated: bool) -> None:
    c = seated(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            (made,) = await add_all(PostgresMemory(db), c.home, c.talk, [
                new(c.alana, "Alana is allergic to shellfish", kind="diet", standing=said, visibility=visibility,
                    stated=stated)])
            assert column(db_url, made, "standing") is True
            assert column(db_url, made, "visibility") == visibility
            assert column(db_url, made, "kind") == "diet"

    run(scenario())


def test_an_update_to_a_diet_is_standing_too(db_url: str) -> None:
    c = seated(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            (first,) = await add_all(memory, c.home, c.talk, [new(c.alana, "Alana eats meat", standing=False)])
            (second,) = await memory.apply(c.home, c.talk, [Update(first, new(
                c.alana, "Alana is vegetarian", kind="diet", standing=False))], LATER)
            assert column(db_url, first, "standing") is False
            assert column(db_url, second, "standing") is True

    run(scenario())


@pytest.mark.parametrize("said", [True, False])
def test_health_is_still_pinned_private_unless_stated_and_keeps_the_standing_it_was_given(db_url: str,
                                                                                         said: bool) -> None:
    c = seated(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            pinned, stated = await add_all(PostgresMemory(db), c.home, c.talk, [
                new(c.alana, "Alana has asthma", kind="health", standing=said, stated=False),
                new(c.alana, "Alana has hay fever", kind="health", standing=said, stated=True)])
            assert column(db_url, pinned, "visibility") == "private"
            assert column(db_url, stated, "visibility") == "shared"
            assert column(db_url, pinned, "standing") is said and column(db_url, stated, "standing") is said

    run(scenario())


@pytest.mark.parametrize("said", [True, False])
def test_finance_is_the_households_unless_stated_and_keeps_the_standing_it_was_given(db_url: str, said: bool) -> None:
    c = seated(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            pinned, stated = await add_all(PostgresMemory(db), c.home, c.talk, [
                new(c.alana, "Alana's savings account holds a deposit for the house", kind="finance", standing=said,
                    stated=False),
                new(c.alana, "Alana's rent is paid on the first", kind="finance", standing=said, stated=True)])
            assert column(db_url, pinned, "kind") == "finance"
            assert column(db_url, pinned, "visibility") == "members"
            assert column(db_url, pinned, "owner_id") is None
            assert column(db_url, stated, "visibility") == "shared"
            assert column(db_url, pinned, "standing") is said and column(db_url, stated, "standing") is said

    run(scenario())


@pytest.mark.parametrize("kind", OTHER_KINDS)
@pytest.mark.parametrize("said", [True, False])
def test_every_other_kind_keeps_the_standing_the_op_gave_it(db_url: str, kind: Kind, said: bool) -> None:
    c = seated(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            (made,) = await add_all(PostgresMemory(db), c.home, c.talk, [new(c.alana, "something", kind=kind,
                                                                           standing=said)])
            assert column(db_url, made, "standing") is said
            assert column(db_url, made, "kind") == kind

    run(scenario())


def test_a_standing_flag_that_is_not_pinned_is_stored_as_given_on_an_inserted_fact_read_back(db_url: str) -> None:
    c = seated(db_url)

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            await memory.apply(c.home, c.talk, [Add(new(c.alana, "Alana uses she/her", kind="person", standing=True)),
                                                Add(new(c.alana, "Alana likes a band", kind="preference",
                                                        standing=False))], AT)
            got = await memory.profile(asker(c.home, c.alana))
            assert [r.fact.text for r in got] == ["Alana uses she/her"]

    run(scenario())


def test_the_profile_log_line_has_household_count_and_ids_and_never_text(db_url: str,
                                                                       capsys: pytest.CaptureFixture[str]) -> None:
    c = seated(db_url)
    logs.setup({"LOG_LEVEL": "info"})

    async def scenario() -> None:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            a, b = await add_all(memory, c.home, c.talk, [new(c.alana, "Alana hides zqxplanted"),
                                                         new(c.alana, "Alana keeps zqxplanted too", kind="diet")])
            capsys.readouterr()
            got = await memory.profile(asker(c.home, c.alana, True))
            assert [r.fact.id for r in got] == [a, b]
            out = capsys.readouterr().out
            (line,) = events(out, "memory.profile")
            values = set(line.values())
            assert str(c.home) in values and "2" in values and f"{a},{b}" in values
            assert "zqxplanted" not in out and "hides" not in out

    run(scenario())


def test_the_null_memory_cannot_say_what_she_always_knows() -> None:
    async def scenario() -> None:
        with pytest.raises(MemoryUnavailable):
            await Memory.null().profile(asker(1))

    run(scenario())

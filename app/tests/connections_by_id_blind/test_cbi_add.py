"""`Connections.add`: a new connection by label, the per-kind limit (`TooMany`), the label rule (`LabelTaken`), who is
refused (`ValueError`), and that the secret is sealed bound to (household, kind, owner)."""

import logging
from datetime import UTC, datetime

import pytest
from ashley.connections.connections import LabelTaken, TooMany
from ashley.connections.sealing import Sealer, Unsealable, bound_to
from connections_by_id_blind_support import KEY, URL, People, add, connections, go, one, rows


def test_an_added_connection_carries_what_it_was_given(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            made = await c.add(people.home, "multi", "work", URL, "the-secret", people.alana)
            assert (made.household_id, made.kind, made.label, made.base_url, made.added_by, made.person_id) == (
                people.home, "multi", "work", URL, people.alana, None)
            assert abs((made.checked_at - made.added_at).total_seconds()) < 5
            assert abs((datetime.now(UTC) - made.added_at).total_seconds()) < 60
            opened = await c.opened(made.id, people.home)
            assert opened is not None and opened.secret == "the-secret" and opened.connection == made
            assert "the-secret" not in repr(opened) and "the-secret" not in repr(made)

    go(scenario())


def test_a_personal_connection_is_owned_by_whoever_added_it(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            made = await c.add(people.home, "own", "mine", URL, "k", people.sam)
            assert made.person_id == people.sam and made.added_by == people.sam

    go(scenario())


def test_each_added_connection_has_its_own_id(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            ids = {await add(c, people.home, people.alana, "multi", label) for label in ("a", "b", "c")}
            assert len(ids) == 3

    go(scenario())


# --- the limit --------------------------------------------------------------------------------------------------------


def test_a_kind_with_most_three_takes_three_and_refuses_the_fourth(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            for label in ("a", "b", "c"):
                await add(c, people.home, people.alana, "multi", label)
            with pytest.raises(TooMany) as raised:
                await add(c, people.home, people.alana, "multi", "d")
            assert raised.value.kind == "multi"
            assert [x.label for x in await c.of_household(people.home, people.alana)] == ["a", "b", "c"]
            assert rows(db_url) == 3

    go(scenario())


def test_a_kind_with_most_one_takes_one_and_refuses_the_second_leaving_the_first_whole(db_url: str,
                                                                                       people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            first = await add(c, people.home, people.alana, "solo", "one", secret="first-secret")
            with pytest.raises(TooMany) as raised:
                await add(c, people.home, people.alana, "solo", "two", secret="second-secret")
            assert raised.value.kind == "solo"
            kept = await c.opened(first, people.home)
            assert kept is not None and kept.secret == "first-secret" and kept.connection.label == "one"
            assert rows(db_url) == 1

    go(scenario())


def test_the_limit_of_a_household_kind_is_the_households_not_each_members(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await add(c, people.home, people.alana, "multi", "a")
            await add(c, people.home, people.sam, "multi", "b")
            await add(c, people.home, people.alana, "multi", "c")
            with pytest.raises(TooMany):
                await add(c, people.home, people.sam, "multi", "d")

    go(scenario())


def test_the_limit_of_a_personal_kind_is_each_persons_own(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            for label in ("a", "b", "c"):
                await add(c, people.home, people.alana, "own", label)
            with pytest.raises(TooMany):
                await add(c, people.home, people.alana, "own", "d")
            for label in ("a", "b", "c"):
                await add(c, people.home, people.sam, "own", label)
            with pytest.raises(TooMany):
                await add(c, people.home, people.sam, "own", "d")
            assert rows(db_url) == 6

    go(scenario())


def test_a_personal_kind_with_most_one_is_one_per_person(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await add(c, people.home, people.alana, "single_own", "a")
            await add(c, people.home, people.sam, "single_own", "a")
            with pytest.raises(TooMany):
                await add(c, people.home, people.alana, "single_own", "b")

    go(scenario())


def test_the_limit_is_per_household_and_per_kind(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            for label in ("a", "b", "c"):
                await add(c, people.home, people.alana, "multi", label)
            for label in ("a", "b", "c"):
                await add(c, people.other, people.kim, "multi", label)
            await add(c, people.home, people.alana, "solo", "a")
            await add(c, people.home, people.alana, "big", "a")
            assert rows(db_url) == 8

    go(scenario())


def test_removing_one_frees_its_place(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            ids = [await add(c, people.home, people.alana, "multi", label) for label in ("a", "b", "c")]
            assert await c.remove(ids[1], people.home, people.alana) is True
            await add(c, people.home, people.alana, "multi", "d")
            with pytest.raises(TooMany):
                await add(c, people.home, people.alana, "multi", "e")

    go(scenario())


# --- labels ----------------------------------------------------------------------------------------------------------


def test_a_label_the_owner_already_has_for_that_kind_is_taken_and_nothing_is_written(db_url: str,
                                                                                    people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            first = await add(c, people.home, people.alana, "multi", "work", secret="first-secret")
            with pytest.raises(LabelTaken) as raised:
                await add(c, people.home, people.sam, "multi", "work", secret="second-secret")
            assert raised.value.kind == "multi"
            kept = await c.opened(first, people.home)
            assert kept is not None and kept.secret == "first-secret"
            assert rows(db_url) == 1

    go(scenario())


def test_the_empty_label_is_allowed_once(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            made = await c.add(people.home, "multi", "", URL, "k", people.alana)
            assert made.label == ""
            with pytest.raises(LabelTaken):
                await add(c, people.home, people.alana, "multi", "")

    go(scenario())


def test_labels_are_compared_exactly_not_by_case_or_whitespace(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            for label in ("work", "Work", "work ", " work", "WORK", ""):
                await add(c, people.home, people.alana, "big", label)
            got = sorted(x.label for x in await c.of_household(people.home))
            assert got == sorted(["work", "Work", "work ", " work", "WORK", ""])

    go(scenario())


def test_a_label_is_free_for_another_owner_kind_or_household(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await add(c, people.home, people.alana, "own", "x")
            await add(c, people.home, people.sam, "own", "x")
            await add(c, people.home, people.alana, "multi", "x")
            await add(c, people.home, people.alana, "big", "x")
            await add(c, people.other, people.kim, "multi", "x")
            assert rows(db_url) == 5

    go(scenario())


# --- who may be an adder, which kinds -----------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["multi", "own"])
def test_an_adder_who_is_not_of_the_household_is_a_value_error_and_nothing_is_written(db_url: str, people: People,
                                                                                    kind: str) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            with pytest.raises(ValueError):
                await c.add(people.home, kind, "x", URL, "k", people.kim)
            with pytest.raises(ValueError):
                await c.add(people.home, kind, "x", URL, "k", 10**7)
            assert rows(db_url) == 0

    go(scenario())


def test_a_kind_nobody_registered_is_a_value_error_and_nothing_is_written(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            with pytest.raises(ValueError):
                await c.add(people.home, "jukebox", "x", URL, "k", people.alana)
            assert rows(db_url) == 0

    go(scenario())


# --- sealing and logs ------------------------------------------------------------------------------------------------------


def _opens(sealed: bytes, bound: bytes) -> bool:
    try:
        return Sealer({1: KEY}, current=1).open(bytes(sealed), bound) == "sealed-secret"
    except Unsealable:
        return False


def test_a_household_secret_is_sealed_bound_to_household_and_kind_whatever_its_label(db_url: str,
                                                                                    people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            ids = [await add(c, people.home, people.alana, "multi", label, secret="sealed-secret")
                   for label in ("a", "b")]
            for i in ids:
                sealed = one(db_url, "SELECT secret FROM connections WHERE id = %s", (i,))
                assert _opens(sealed, bound_to(people.home, "multi"))
                assert not _opens(sealed, bound_to(people.home, "solo"))
                assert not _opens(sealed, bound_to(people.other, "multi"))

    go(scenario())


def test_a_personal_secret_is_sealed_bound_to_its_person_too(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            i = await add(c, people.home, people.alana, "own", "a", secret="sealed-secret")
            sealed = one(db_url, "SELECT secret FROM connections WHERE id = %s", (i,))
            assert _opens(sealed, bound_to(people.home, "own", people.alana))
            assert not _opens(sealed, bound_to(people.home, "own", people.sam))
            assert not _opens(sealed, bound_to(people.home, "own"))

    go(scenario())


def test_an_add_is_logged_with_its_connection_and_never_its_secret(db_url: str, people: People,
                                                                    caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    async def scenario() -> int:
        async with connections(db_url) as c:
            return await add(c, people.home, people.alana, "multi", "a", secret="log-me-not-0001")

    made = go(scenario())
    text = "\n".join(f"{r.name} {r.getMessage()} {getattr(r, 'fields', {})!r}" for r in caplog.records)
    assert "connections.added" in text and "log-me-not-0001" not in text
    line = next(r for r in caplog.records if "connections.added" in r.getMessage())
    assert str(made) in f"{line.getMessage()} {getattr(line, 'fields', {})!r}"

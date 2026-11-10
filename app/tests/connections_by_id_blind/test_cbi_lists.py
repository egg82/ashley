"""`Connections.of_household` order and visibility, `seed`, the Null Object, the deleted kind-keyed methods, and rows
that existed before labels."""

import pytest
from ashley.connections.connections import Connections, ConnectionsUnavailable, LabelTaken
from ashley.connections.sealing import Sealer, bound_to
from connections_by_id_blind_support import KEY, URL, People, add, connections, go, one, rows


def test_of_household_is_ordered_by_kind_then_label_then_id(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            for kind, label in (("multi", "b"), ("big", "z"), ("multi", ""), ("big", "a"), ("multi", "a"),
                                ("big", "")):
                await add(c, people.home, people.alana, kind, label)
            got = [(x.kind, x.label) for x in await c.of_household(people.home)]
            assert got == [("big", ""), ("big", "a"), ("big", "z"), ("multi", ""), ("multi", "a"), ("multi", "b")]

    go(scenario())


def test_a_personal_kind_sorts_in_among_the_rest_by_its_kind(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            for kind in ("solo", "own", "multi"):
                await add(c, people.home, people.alana, kind, "x")
            assert [x.kind for x in await c.of_household(people.home, people.alana)] == ["multi", "own", "solo"]

    go(scenario())


def test_of_household_shows_a_person_only_the_households_and_their_own(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await add(c, people.home, people.alana, "multi", "h")
            await add(c, people.home, people.alana, "own", "alanas")
            await add(c, people.home, people.sam, "own", "sams")
            await add(c, people.other, people.kim, "multi", "kims")
            labels = {p: sorted(x.label for x in await c.of_household(people.home, p))
                      for p in (people.alana, people.sam, None)}
            assert labels == {people.alana: ["alanas", "h"], people.sam: ["h", "sams"], None: ["h"]}
            assert [x.label for x in await c.of_household(people.other, people.kim)] == ["kims"]

    go(scenario())


# --- seed ---------------------------------------------------------------------------------------------------------------


def test_seed_adds_the_unlabelled_connection_where_the_household_has_none_of_that_kind(db_url: str,
                                                                                      people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            made = await c.seed(people.home, "multi", URL, "seeded-secret")
            assert made is not None and made.label == "" and made.added_by is None and made.person_id is None
            opened = await c.opened(made.id, people.home)
            assert opened is not None and opened.secret == "seeded-secret"
            assert await c.seed(people.home, "multi", URL, "again") is None
            assert rows(db_url) == 1

    go(scenario())


def test_seed_does_nothing_where_the_household_holds_any_of_that_kind(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await add(c, people.home, people.alana, "multi", "work")
            assert await c.seed(people.home, "multi", URL, "seeded-secret") is None
            assert [x.label for x in await c.of_household(people.home)] == ["work"]
            assert await c.seed(people.home, "solo", URL, "other-kind") is not None
            assert await c.seed(people.other, "multi", URL, "other-home") is not None

    go(scenario())


# --- the Null Object and the deleted methods ---------------------------------------------------------------------------------


@pytest.mark.parametrize("call", ["add", "replace", "relabel", "remove", "opened", "of_household"])
def test_the_null_object_raises_unavailable_for_every_method(call: str) -> None:
    null = Connections.null()
    attempts = {
        "add": lambda: null.add(1, "multi", "a", URL, "k", 1),
        "replace": lambda: null.replace(1, 1, 1, URL, "k"),
        "relabel": lambda: null.relabel(1, 1, 1, "a"),
        "remove": lambda: null.remove(1, 1, 1),
        "opened": lambda: null.opened(1, 1, 1),
        "of_household": lambda: null.of_household(1, 1)}

    with pytest.raises(ConnectionsUnavailable):
        go(attempts[call]())


def test_the_kind_keyed_put_is_gone() -> None:
    assert not hasattr(Connections, "put")


# --- before labels ---------------------------------------------------------------------------------------------------------


def test_a_row_written_without_a_label_reads_back_with_the_empty_label(db_url: str, people: People) -> None:
    """What a connection stored before labels looks like: the row has no label to give, so the column's default is it."""
    sealed = Sealer({1: KEY}, current=1).seal("old-secret", bound_to(people.home, "multi"))

    async def scenario() -> None:
        async with connections(db_url) as c:
            old = one(db_url, "INSERT INTO connections (household_id, kind, base_url, secret, added_by) "
                              "VALUES (%s, 'multi', %s, %s, %s) RETURNING id", (people.home, URL, sealed, people.alana))
            listed = await c.of_household(people.home)
            assert [(x.id, x.label) for x in listed] == [(old, "")]
            opened = await c.opened(old, people.home)
            assert opened is not None and opened.secret == "old-secret" and opened.connection.label == ""
            with pytest.raises(LabelTaken):
                await add(c, people.home, people.alana, "multi", "")

    go(scenario())


def test_the_label_column_is_never_null(db_url: str) -> None:
    assert one(db_url, "SELECT is_nullable FROM information_schema.columns "
                       "WHERE table_name = 'connections' AND column_name = 'label'") == "NO"

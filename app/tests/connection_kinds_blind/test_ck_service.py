"""The Connections service (`ashley.connections.connections.Connections`) on the real Postgres implementation: one
connection per household and kind, a code host's per person, the secret sealed bound to its row, only registered
kinds, `seed`, `remove`, `answered`, and the Null Object."""

import logging

import pytest
from ashley.connections.connections import Connections, ConnectionsUnavailable
from ashley.connections.kinds import ConnectionKinds
from connection_kinds_blind_support import (ADDRESSES, KIND_NAMES, SECRETS, People, all_logs, connections, go, hold,
                                            kind_named, log_text, scalar, stored_at)
from ashley import services
from ashley.wiring import CONNECTION_KINDS
from connection_legacy_support import opened_of, put_of, remove_of


def test_a_connection_is_stored_and_opened_with_its_secret(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            made = await put_of(c, people.home, "sure", ADDRESSES["sure"], SECRETS["sure"], people.alana)
            assert (made.household_id, made.kind, made.base_url, made.added_by, made.person_id) == (
                people.home, "sure", ADDRESSES["sure"], people.alana, None)
            opened = await opened_of(c, people.home, "sure")
            assert opened is not None and opened.secret == SECRETS["sure"] and opened.connection == made
            assert SECRETS["sure"] not in repr(opened) and SECRETS["sure"] not in repr(made)

    go(scenario())


def test_opened_is_none_for_a_household_without_one(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await hold(c, people.home, people.alana, "sure")
            assert await opened_of(c, people.other, "sure") is None
            assert await opened_of(c, people.home, "home_assistant") is None

    go(scenario())


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_a_new_connection_has_added_and_checked_now(db_url: str, people: People, kind: str) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await hold(c, people.home, people.alana, kind)
            got = (await c.of_household(people.home, people.alana))[0]
            assert abs((got.checked_at - got.added_at).total_seconds()) < 5

    go(scenario())


def test_a_second_put_makes_added_and_checked_now_again(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await hold(c, people.home, people.alana, "sure")
            scalar(db_url, "UPDATE connections SET added_at = added_at - interval '1 hour', "
                           "checked_at = checked_at - interval '1 hour' RETURNING 1")
            before = scalar(db_url, "SELECT added_at FROM connections")
            again = await put_of(c, people.home, "sure", ADDRESSES["sure"], "the-replacement", people.sam)
            assert again.added_at > before and again.checked_at > before and again.added_by == people.sam

    go(scenario())


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_a_second_put_replaces_the_first(db_url: str, people: People, kind: str) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await hold(c, people.home, people.alana, kind)
            await hold(c, people.home, people.alana, kind, secret="the-replacement")
            assert len(await c.of_household(people.home, people.alana)) == 1
            opened = await opened_of(c, people.home, kind, people.alana if kind_named(kind).default_holder == "person" else None)
            assert opened is not None and opened.secret == "the-replacement"

    go(scenario())


def test_a_household_connection_is_one_per_household_whoever_adds_it(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await hold(c, people.home, people.alana, "sure")
            await hold(c, people.home, people.sam, "sure", secret="sams")
            got = await c.of_household(people.home)
            assert [(x.kind, x.added_by) for x in got] == [("sure", people.sam)]

    go(scenario())


def test_a_code_host_is_one_per_person_and_carries_the_person(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await hold(c, people.home, people.alana, "gitlab")
            await hold(c, people.home, people.sam, "gitlab", secret="sams-token")
            a, s = await opened_of(c, people.home, "gitlab", people.alana), await opened_of(c, people.home, "gitlab", people.sam)
            assert a is not None and s is not None
            assert (a.secret, a.connection.person_id) == (SECRETS["gitlab"], people.alana)
            assert (s.secret, s.connection.person_id) == ("sams-token", people.sam)

    go(scenario())


def test_the_stored_person_is_set_for_exactly_the_personal_kinds(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            for kind in KIND_NAMES:
                await hold(c, people.home, people.alana, kind)
            held = {k: scalar(db_url, "SELECT person_id FROM connections WHERE kind = %s", (k,)) for k in KIND_NAMES}
            assert held == {k: people.alana if kind_named(k).default_holder == "person" else None for k in KIND_NAMES}

    go(scenario())


def test_a_listing_holds_the_households_and_only_the_named_persons_own(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await hold(c, people.home, people.alana, "sure")
            await hold(c, people.home, people.alana, "gitlab")
            await hold(c, people.home, people.sam, "github")
            await hold(c, people.other, people.kim, "home_assistant")
            kinds = {p: sorted(x.kind for x in await c.of_household(people.home, p)) for p in (None, people.alana, people.sam)}
            assert kinds == {None: ["sure"], people.alana: ["gitlab", "sure"], people.sam: ["github", "sure"]}
            assert [x.kind for x in await c.of_household(people.other)] == ["home_assistant"]

    go(scenario())


def test_removing_a_personal_connection_removes_only_that_persons(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await hold(c, people.home, people.alana, "github")
            await hold(c, people.home, people.sam, "github")
            assert await remove_of(c, people.home, "github", people.alana) is True
            assert await opened_of(c, people.home, "github", people.alana) is None
            assert await opened_of(c, people.home, "github", people.sam) is not None
            assert await remove_of(c, people.home, "github", people.alana) is False

    go(scenario())


def test_removing_a_household_connection_removes_it_and_says_false_the_second_time(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await hold(c, people.home, people.alana, "sure")
            await hold(c, people.other, people.kim, "sure")
            assert await remove_of(c, people.home, "sure") is True and await remove_of(c, people.home, "sure") is False
            assert await opened_of(c, people.home, "sure") is None and await opened_of(c, people.other, "sure") is not None

    go(scenario())


def test_an_adder_who_is_not_of_the_household_is_refused_and_nothing_is_written(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            with pytest.raises(ValueError):
                await put_of(c, people.home, "sure", ADDRESSES["sure"], SECRETS["sure"], people.kim)
            assert await c.of_household(people.home) == ()

    go(scenario())


def test_only_registered_kinds_are_written(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            with pytest.raises((ValueError, ConnectionsUnavailable)):
                await put_of(c, people.home, "jukebox", "https://music.test", "tok", people.alana)
            services.register(ConnectionKinds, ConnectionKinds(tuple(k for k in CONNECTION_KINDS if k.name != "sure")))
            with pytest.raises((ValueError, ConnectionsUnavailable)):
                await hold(c, people.home, people.alana, "sure")
            assert scalar(db_url, "SELECT count(*) FROM connections") == 0

    go(scenario())


def test_a_row_whose_kind_is_no_longer_registered_is_not_read(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await hold(c, people.home, people.alana, "sure")
            await hold(c, people.home, people.alana, "home_assistant")
            services.register(ConnectionKinds, ConnectionKinds.null())
            with pytest.raises(ConnectionsUnavailable):
                await c.of_household(people.home)
            with pytest.raises(ConnectionsUnavailable):
                await opened_of(c, people.home, "sure")

    go(scenario())


def test_a_secret_moved_under_another_row_does_not_open(db_url: str, people: People, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await hold(c, people.home, people.alana, "sure")
            await hold(c, people.home, people.alana, "home_assistant")
            scalar(db_url, "UPDATE connections SET secret = (SELECT secret FROM connections WHERE kind = 'sure') "
                           "WHERE kind = 'home_assistant' RETURNING 1")
            with pytest.raises(ConnectionsUnavailable):
                await opened_of(c, people.home, "home_assistant")
            assert (await opened_of(c, people.home, "sure")) is not None

    all_logs(caplog)
    go(scenario())
    text = log_text(caplog)
    sealed = bytes(scalar(db_url, "SELECT secret FROM connections WHERE kind = 'sure'"))
    assert SECRETS["sure"] not in text and sealed.hex() not in text and "unsealable" in text


def test_a_personal_secret_moved_to_another_person_does_not_open(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await hold(c, people.home, people.alana, "gitlab")
            await hold(c, people.home, people.sam, "gitlab", secret="sams-token")
            scalar(db_url, "UPDATE connections SET secret = (SELECT secret FROM connections WHERE person_id = %s) "
                           "WHERE person_id = %s RETURNING 1", (people.alana, people.sam))
            with pytest.raises(ConnectionsUnavailable):
                await opened_of(c, people.home, "gitlab", people.sam)

    go(scenario())


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_the_secret_is_not_stored_in_the_clear(db_url: str, people: People, kind: str) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await hold(c, people.home, people.alana, kind)
            stored = bytes(scalar(db_url, "SELECT secret FROM connections"))
            assert stored and SECRETS[kind].encode() not in stored

    go(scenario())


# --- seed ---------------------------------------------------------------------------------------------------------------


def test_seed_adds_a_connection_with_no_adder_only_where_there_is_none(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            seeded = await c.seed(people.home, "home_assistant", ADDRESSES["home_assistant"], "seeded-token")
            assert seeded is not None and seeded.added_by is None and seeded.kind == "home_assistant"
            assert await c.seed(people.home, "home_assistant", "http://other.test", "second") is None
            opened = await opened_of(c, people.home, "home_assistant")
            assert opened is not None and opened.secret == "seeded-token"
            assert opened.connection.base_url == ADDRESSES["home_assistant"]

    go(scenario())


def test_seed_never_replaces_a_connection_a_person_added(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await hold(c, people.home, people.alana, "home_assistant")
            assert await c.seed(people.home, "home_assistant", "http://other.test", "seeded") is None
            opened = await opened_of(c, people.home, "home_assistant")
            assert opened is not None and opened.secret == SECRETS["home_assistant"]

    go(scenario())


def test_seed_for_a_household_that_does_not_exist_writes_nothing(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            assert await c.seed(9999, "home_assistant", ADDRESSES["home_assistant"], "t") is None
            assert scalar(db_url, "SELECT count(*) FROM connections") == 0

    go(scenario())


# --- answered ---------------------------------------------------------------------------------------------------------------


def test_answered_moves_that_connections_checked_at_and_nothing_else(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            mine = await hold(c, people.home, people.alana, "sure")
            await hold(c, people.home, people.alana, "home_assistant")
            scalar(db_url, "UPDATE connections SET checked_at = checked_at - interval '1 hour' RETURNING 1")
            ha_before = stored_at(db_url, people.home, "home_assistant")
            added = scalar(db_url, "SELECT added_at FROM connections WHERE id = %s", (mine,))
            before = stored_at(db_url, people.home, "sure")
            await c.answered(mine)
            assert stored_at(db_url, people.home, "sure") > before
            assert stored_at(db_url, people.home, "home_assistant") == ha_before
            assert scalar(db_url, "SELECT added_at FROM connections WHERE id = %s", (mine,)) == added

    go(scenario())


# --- the Null Object ------------------------------------------------------------------------------------------------------------


def test_the_null_connections_cannot_open_and_cannot_add() -> None:
    async def scenario() -> None:
        null = Connections.null()
        assert null.can_open() is False
        with pytest.raises(ConnectionsUnavailable):
            await put_of(null, 1, "sure", ADDRESSES["sure"], "k", 1)

    go(scenario())


# --- logs ------------------------------------------------------------------------------------------------------------------------


def test_put_seed_and_remove_each_log_and_none_carries_the_secret(db_url: str, people: People,
                                                                  caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await hold(c, people.home, people.alana, "sure")
            await c.seed(people.home, "home_assistant", ADDRESSES["home_assistant"], "seeded-token-xyz")
            await remove_of(c, people.home, "sure")

    all_logs(caplog)
    go(scenario())
    events = {r.getMessage() for r in caplog.records}
    assert {"connections.added", "connections.seeded", "connections.removed"} <= events
    text = log_text(caplog)
    assert SECRETS["sure"] not in text and "seeded-token-xyz" not in text
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

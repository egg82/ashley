"""A person's own code-host connections on a real database: one per person and kind, listed, opened and removed only by
naming their person, the secret sealed bound to household, kind and person, and never in a repr, a log or the table."""

import os
import re

import psycopg
import pytest
from ashley import services
from ashley.connections import address
from ashley.connections.connections import Connections, ConnectionsUnavailable, NullConnections
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.model import Kind
from ashley.connections.sealing import Sealer, Unsealable, bound_to
from contract.conversations_support import scalar
from hos_support import GITHUB_API, GITLAB, all_logs, connect, connections, fields_of, go, log_text, world
from connection_legacy_support import opened_of, put_of, remove_of


pytestmark = pytest.mark.usefixtures("connection_kinds_wired")

SECRET_A, SECRET_B = "glpat-secret-of-alana-aaaa", "glpat-secret-of-sam-bbbb"  # gitleaks:allow (test fixture)


def test_the_personal_kinds_are_the_code_hosts_herdr_and_google() -> None:
    personal = {k.name for k in services.get(ConnectionKinds).all() if k.default_holder == "person"}
    assert personal == {"gitlab", "github", "herdr", "google"}


def test_a_person_opens_their_own_and_no_one_elses(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with connections(db_url) as c:
            await connect(c, w.alana, w.home, "gitlab", SECRET_A)
            await connect(c, w.sam, w.home, "gitlab", SECRET_B)
            mine, theirs = await opened_of(c, w.home, "gitlab", w.alana), await opened_of(c, w.home, "gitlab", w.sam)
            assert mine is not None and mine.secret == SECRET_A and mine.connection.person_id == w.alana
            assert theirs is not None and theirs.secret == SECRET_B and theirs.connection.person_id == w.sam
            assert await opened_of(c, w.home, "gitlab", w.lee) is None
            assert await opened_of(c, w.home, "github", w.alana) is None

    go(scenario())


def test_a_person_of_another_household_opens_nothing_of_this_ones(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with connections(db_url) as c:
            await connect(c, w.alana, w.home, "gitlab", SECRET_A)
            assert await opened_of(c, w.other, "gitlab", w.kim) is None
            assert await opened_of(c, w.other, "gitlab", w.alana) is None
            assert await opened_of(c, w.home, "gitlab", w.kim) is None

    go(scenario())


async def opened_secret(c: Connections, household: int, kind: Kind, person: int | None) -> str | None:
    """The secret an open gives, None when it gives none or refuses; any other outcome is the test's failure."""
    try:
        got = await opened_of(c, household, kind, person)
    except (ConnectionsUnavailable, ValueError):
        return None
    return None if got is None else got.secret


def test_naming_no_person_opens_no_ones_personal_connection(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with connections(db_url) as c:
            await connect(c, w.alana, w.home, "gitlab", SECRET_A)
            assert await opened_secret(c, w.home, "gitlab", None) is None

    go(scenario())


def test_the_listing_holds_the_households_and_the_askers_own_but_never_another_persons(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with connections(db_url) as c:
            await put_of(c, w.home, "sure", "https://money.test", "sure-key", w.alana)
            await connect(c, w.alana, w.home, "gitlab", SECRET_A)
            await connect(c, w.sam, w.home, "gitlab", SECRET_B)
            await connect(c, w.sam, w.home, "github", "ghp-sam", GITHUB_API)
            kinds_of = {p: sorted((x.kind, x.person_id) for x in await c.of_household(w.home, p))
                        for p in (w.alana, w.sam, w.lee)}
            assert kinds_of[w.alana] == [("gitlab", w.alana), ("sure", None)]
            assert kinds_of[w.sam] == [("github", w.sam), ("gitlab", w.sam), ("sure", None)]
            assert kinds_of[w.lee] == [("sure", None)]
            assert sorted((x.kind, x.person_id) for x in await c.of_household(w.home)) == [("sure", None)]
            assert await c.of_household(w.other, w.kim) == ()
            assert await c.of_household(w.other, w.alana) == ()

    go(scenario())


def test_a_person_removes_only_their_own(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with connections(db_url) as c:
            await connect(c, w.alana, w.home, "gitlab", SECRET_A)
            await connect(c, w.sam, w.home, "gitlab", SECRET_B)
            assert await remove_of(c, w.home, "gitlab", w.lee) is False
            assert await remove_of(c, w.other, "gitlab", w.alana) is False
            assert await remove_of(c, w.other, "gitlab", w.kim) is False
            assert await opened_secret(c, w.home, "gitlab", w.alana) == SECRET_A
            assert await opened_secret(c, w.home, "gitlab", w.sam) == SECRET_B
            assert await remove_of(c, w.home, "gitlab", w.alana) is True
            assert await remove_of(c, w.home, "gitlab", w.alana) is False
            assert await opened_secret(c, w.home, "gitlab", w.alana) is None
            assert await opened_secret(c, w.home, "gitlab", w.sam) == SECRET_B

    go(scenario())
    assert scalar(db_url, "SELECT count(*) FROM connections") == 1


def test_removing_with_no_person_removes_no_ones_personal_connection(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with connections(db_url) as c:
            await connect(c, w.alana, w.home, "gitlab", SECRET_A)
            try:
                assert await remove_of(c, w.home, "gitlab", None) is False
            except (ConnectionsUnavailable, ValueError):
                pass
            assert await opened_secret(c, w.home, "gitlab", w.alana) == SECRET_A

    go(scenario())


def test_one_per_person_and_kind_a_second_put_replaces_it(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with connections(db_url) as c:
            first = await put_of(c, w.home, "gitlab", GITLAB, "first", w.alana)
            await connect(c, w.sam, w.home, "gitlab", SECRET_B)
            second = await put_of(c, w.home, "gitlab", "https://other.test", "second", w.alana)
            assert first.person_id == second.person_id == w.alana
            now = await opened_of(c, w.home, "gitlab", w.alana)
            assert now is not None and (now.secret, now.connection.base_url) == ("second", "https://other.test")
            assert await opened_secret(c, w.home, "gitlab", w.sam) == SECRET_B
            assert len([x for x in await c.of_household(w.home, w.alana) if x.kind == "gitlab"]) == 1

    go(scenario())
    assert scalar(db_url, "SELECT count(*) FROM connections") == 2


def test_a_person_can_hold_a_gitlab_and_a_github_at_once(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with connections(db_url) as c:
            await connect(c, w.alana, w.home, "gitlab", "gl-token")
            await connect(c, w.alana, w.home, "github", "gh-token")
            assert await opened_secret(c, w.home, "gitlab", w.alana) == "gl-token"
            assert await opened_secret(c, w.home, "github", w.alana) == "gh-token"
            assert await remove_of(c, w.home, "gitlab", w.alana) is True
            assert await opened_secret(c, w.home, "github", w.alana) == "gh-token"

    go(scenario())


def test_a_put_by_a_person_of_another_household_is_refused_and_writes_nothing(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with connections(db_url) as c:
            with pytest.raises(ValueError):
                await put_of(c, w.home, "gitlab", GITLAB, "token", w.kim)
            assert await c.of_household(w.home, w.kim) == () and await c.of_household(w.other, w.kim) == ()

    go(scenario())
    assert scalar(db_url, "SELECT count(*) FROM connections") == 0


def test_the_household_kinds_stay_the_households_whoever_asks(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with connections(db_url) as c:
            put = await put_of(c, w.home, "sure", "https://money.test", "sure-key", w.alana)
            assert put.person_id is None
            assert await opened_secret(c, w.home, "sure", None) == "sure-key"
            for p in (w.alana, w.sam, w.lee):
                assert "sure" in {x.kind for x in await c.of_household(w.home, p)}

    go(scenario())


def test_a_secret_copied_to_another_persons_row_does_not_open(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    w = world(db_url)
    all_logs(caplog)

    async def put() -> None:
        async with connections(db_url) as c:
            await connect(c, w.alana, w.home, "gitlab", SECRET_A)
            await connect(c, w.sam, w.home, "gitlab", SECRET_B)

    go(put())
    sealed = bytes(scalar(db_url, "SELECT secret FROM connections WHERE person_id = %s", (w.alana,)))
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("UPDATE connections SET secret = (SELECT secret FROM connections WHERE person_id = %s) "
                     "WHERE person_id = %s", (w.alana, w.sam))

    async def read() -> None:
        async with connections(db_url) as c:
            with pytest.raises(ConnectionsUnavailable):
                await opened_of(c, w.home, "gitlab", w.sam)
            mine = await opened_of(c, w.home, "gitlab", w.alana)
            assert mine is not None and mine.secret == SECRET_A

    go(read())
    assert len(fields_of(caplog, "connections.unsealable")) >= 1
    assert SECRET_A not in log_text(caplog) and SECRET_B not in log_text(caplog)
    assert sealed.hex() not in log_text(caplog) and repr(sealed) not in log_text(caplog)


def test_a_secret_moved_to_another_kind_of_the_same_person_does_not_open(db_url: str) -> None:
    w = world(db_url)

    async def put() -> None:
        async with connections(db_url) as c:
            await connect(c, w.alana, w.home, "gitlab", "gl-token")
            await connect(c, w.alana, w.home, "github", "gh-token")

    go(put())
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("UPDATE connections SET secret = (SELECT secret FROM connections WHERE kind = 'gitlab') "
                     "WHERE kind = 'github'")

    async def read() -> None:
        async with connections(db_url) as c:
            with pytest.raises(ConnectionsUnavailable):
                await opened_of(c, w.home, "github", w.alana)

    go(read())


def test_a_secret_sealed_under_another_key_does_not_open(db_url: str) -> None:
    w = world(db_url)

    async def put() -> None:
        async with connections(db_url, os.urandom(32)) as c:
            await connect(c, w.alana, w.home, "gitlab", SECRET_A)

    go(put())

    async def read() -> None:
        async with connections(db_url) as c:
            with pytest.raises(ConnectionsUnavailable):
                await opened_of(c, w.home, "gitlab", w.alana)

    go(read())


def test_the_secret_is_neither_in_the_table_nor_a_repr_nor_a_log(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    w = world(db_url)
    all_logs(caplog)

    async def scenario() -> None:
        async with connections(db_url) as c:
            put = await put_of(c, w.home, "gitlab", GITLAB, SECRET_A, w.alana)
            listed = await c.of_household(w.home, w.alana)
            opened = await opened_of(c, w.home, "gitlab", w.alana)
            assert opened is not None
            for shown in (repr(put), repr(listed), repr(opened), str(put)):
                assert SECRET_A not in shown
            await c.answered(put.id)
            await remove_of(c, w.home, "gitlab", w.alana)

    go(scenario())
    assert SECRET_A not in log_text(caplog)
    assert fields_of(caplog, "connections.added") and fields_of(caplog, "connections.removed")


def test_the_stored_bytes_hold_no_secret(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with connections(db_url) as c:
            await connect(c, w.alana, w.home, "gitlab", SECRET_A)

    go(scenario())
    assert SECRET_A.encode() not in bytes(scalar(db_url, "SELECT secret FROM connections"))


def test_answered_moves_only_that_connections_checked_at(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with connections(db_url) as c:
            a = await put_of(c, w.home, "gitlab", GITLAB, SECRET_A, w.alana)
            b = await put_of(c, w.home, "gitlab", GITLAB, SECRET_B, w.sam)
            with psycopg.connect(db_url, autocommit=True) as conn:
                conn.execute("UPDATE connections SET checked_at = checked_at - interval '1 day'")
            before = {x.person_id: x.checked_at for p in (w.alana, w.sam) for x in await c.of_household(w.home, p)}
            await c.answered(a.id)
            after = {x.person_id: x.checked_at for p in (w.alana, w.sam) for x in await c.of_household(w.home, p)}
            assert after[w.alana] > before[w.alana] and after[w.sam] == before[w.sam]
            assert b.person_id == w.sam

    go(scenario())


def sealer_bytes() -> bytes:
    return Sealer({1: os.urandom(32)}, current=1).seal("x", b"bound")


def test_a_null_connections_reads_none_and_adds_nothing(db_url: str) -> None:
    w = world(db_url)
    null = NullConnections()

    async def scenario() -> None:
        assert null.can_open() is False
        assert await opened_secret(null, w.home, "gitlab", w.alana) is None
        try:
            assert await null.of_household(w.home, w.alana) == ()
        except ConnectionsUnavailable:
            pass
        with pytest.raises(ConnectionsUnavailable):
            await put_of(null, w.home, "gitlab", GITLAB, SECRET_A, w.alana)

    go(scenario())


# --- sealing, bound to the person --------------------------------------------------------------------------------


def test_a_secret_sealed_for_one_person_does_not_open_as_another() -> None:
    sealer = Sealer({1: os.urandom(32)}, current=1)
    sealed = sealer.seal("token", bound_to(1, "gitlab", 10))
    assert sealer.open(sealed, bound_to(1, "gitlab", 10)) == "token"
    for other in (bound_to(1, "gitlab", 11), bound_to(1, "gitlab"), bound_to(1, "github", 10), bound_to(2, "gitlab", 10)):
        with pytest.raises(Unsealable):
            sealer.open(sealed, other)
    assert len({bound_to(1, "gitlab", 10), bound_to(1, "gitlab", 11), bound_to(1, "gitlab")}) == 3


def test_a_household_secret_does_not_open_as_a_persons() -> None:
    sealer = Sealer({1: os.urandom(32)}, current=1)
    sealed = sealer.seal("token", bound_to(1, "sure"))
    with pytest.raises(Unsealable):
        sealer.open(sealed, bound_to(1, "sure", 10))


# --- the address --------------------------------------------------------------------------------------------------

HTTPS = frozenset({"https"})
WEB = frozenset({"http", "https"})


@pytest.mark.parametrize("text, schemes, want", [
    ("https://gitlab.test", HTTPS, "https://gitlab.test"),
    ("https://gitlab.test/", HTTPS, "https://gitlab.test"),
    ("https://gitlab.test/git", HTTPS, "https://gitlab.test/git"),
    ("https://gitlab.test/git/", HTTPS, "https://gitlab.test/git"),
    ("https://gitlab.test:8443", HTTPS, "https://gitlab.test:8443"),
    ("https://gitlab.test:65535", HTTPS, "https://gitlab.test:65535"),
    ("http://ha.test:8123", WEB, "http://ha.test:8123"),
    ("https://ha.test", WEB, "https://ha.test"),
    ("http://ha.test:8123", HTTPS, None),
    ("ftp://gitlab.test", WEB, None),
    ("gitlab.test", HTTPS, None),
    ("", HTTPS, None),
    ("https://", HTTPS, None),
    ("https:///path", HTTPS, None),
    ("https://user@gitlab.test", HTTPS, None),
    ("https://user:pw@gitlab.test", HTTPS, None),
    ("https://:pw@gitlab.test", HTTPS, None),
    ("https://gitlab.test?x=1", HTTPS, None),
    ("https://gitlab.test/p?x=1", HTTPS, None),
    ("https://gitlab.test#frag", HTTPS, None),
    ("https://gitlab.test/p#frag", HTTPS, None),
    ("https://gitlab.test:70000", HTTPS, None),
    ("https://gitlab.test:65536", HTTPS, None),
    ("https://gitlab.test:0", HTTPS, None),
    ("https://gitlab.test:99999999", HTTPS, None),
    ("javascript:alert(1)", WEB, None),
])
def test_base_url(text: str, schemes: frozenset[str], want: str | None) -> None:
    assert address.base_url(text, schemes) == want


def test_base_url_gives_a_stable_form() -> None:
    once = address.base_url("https://gitlab.test/git/", HTTPS)
    assert once is not None and address.base_url(once, HTTPS) == once and not re.search(r"/$", once)

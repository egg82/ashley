"""`ashley.connections.ports.opened` and `opened_all`: every visible connection of a kind implementing the port, in
kind registration order, then label, then id."""

from ashley.connections import ports
from ashley.connections.kinds import ConnectionKind
from ashley.connections.model import Port
from connections_by_id_blind_support import Checks, People, add, connections, go, kind

HERDR: frozenset[Port] = frozenset({"herdr"})

LEDGER: frozenset[Port] = frozenset({"ledger"})


def kinds() -> tuple[ConnectionKind, ...]:
    check = Checks()
    return (kind("zeta", 3, check, ports=HERDR), kind("alpha", 3, check, ports=HERDR),
            kind("mine", 3, check, personal=True, ports=HERDR), kind("elsewhere", 3, check, ports=LEDGER))


def test_opened_all_is_in_registration_order_then_label_then_id(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url, kinds()) as c:
            for name, label in (("alpha", "x"), ("zeta", "b"), ("zeta", "a"), ("alpha", "")):
                await add(c, people.home, people.alana, name, label, secret=f"{name}-{label}")
            got = await ports.opened_all(c, "herdr", people.home)
            assert [(o.connection.kind, o.connection.label, o.secret) for o in got] == [
                ("zeta", "a", "zeta-a"), ("zeta", "b", "zeta-b"), ("alpha", "", "alpha-"), ("alpha", "x", "alpha-x")]
            first = await ports.opened(c, "herdr", people.home)
            assert first == got[0]

    go(scenario())


def test_a_kind_that_does_not_implement_the_port_is_left_out(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url, kinds()) as c:
            await add(c, people.home, people.alana, "elsewhere", "e")
            assert await ports.opened_all(c, "herdr", people.home) == ()
            assert await ports.opened(c, "herdr", people.home) is None
            assert len(await ports.opened_all(c, "ledger", people.home)) == 1

    go(scenario())


def test_only_what_the_person_can_see_is_opened(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url, kinds()) as c:
            await add(c, people.home, people.alana, "alpha", "h")
            await add(c, people.home, people.alana, "mine", "alanas")
            await add(c, people.home, people.sam, "mine", "sams")
            await add(c, people.other, people.kim, "zeta", "kims")
            seen = {who: [o.connection.label for o in await ports.opened_all(c, "herdr", people.home, who)]
                    for who in (people.alana, people.sam, None)}
            assert seen == {people.alana: ["h", "alanas"], people.sam: ["h", "sams"], None: ["h"]}
            assert [o.connection.label for o in await ports.opened_all(c, "herdr", people.other, people.kim)] == ["kims"]

    go(scenario())


def test_opened_is_the_first_of_those_and_none_when_there_are_none(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url, kinds()) as c:
            assert await ports.opened(c, "herdr", people.home, people.alana) is None
            assert await ports.opened_all(c, "herdr", people.home, people.alana) == ()
            await add(c, people.home, people.alana, "mine", "alanas")
            await add(c, people.home, people.alana, "alpha", "h")
            first = await ports.opened(c, "herdr", people.home, people.alana)
            assert first is not None and first.connection.label == "h"
            only_own = await ports.opened(c, "herdr", people.home, people.sam)
            assert only_own is not None and only_own.connection.label == "h"
            assert await ports.opened(c, "herdr", people.other) is None

    go(scenario())

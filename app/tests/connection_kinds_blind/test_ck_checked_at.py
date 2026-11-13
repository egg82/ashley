"""`HouseholdConnection.checked_at` is "when the service last answered with it, at its adding or on one of her reads
since": for every registered kind, a successful read of hers through that kind's service moves it forward, a read the
service did not answer does not, and a read moves only the connection it was made with."""

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.home_assistant.homes import Homes
from ashley.inference.model import ToolCall
from ashley.sure.ledger import SureLedger
from ashley.tools.code_host import CodeHostTools
from connection_kinds_blind_support import (CODE_HOSTS, KIND_NAMES, SECRETS, Fakes, People, age, connections, go, hold,
                                            kind_named, owner, stored_at)

async def her_read(who: People, kind: str) -> None:
    """One read of hers through the kind's own service as Alana, raising when the service did not answer."""
    if kind == "sure":
        await SureLedger().accounts(who.home, 10)
    elif kind == "home_assistant":
        home = await services.get(Homes).of(who.home)
        assert home is not None
        await home.house.configs("automation")
    else:
        got = await CodeHostTools(who.home, who.alana, None, CODE_HOSTS, 8000).call(ToolCall("c", "git_projects", {"host": kind}))
        assert not got.is_error


async def setup(c: Connections, who: People, fakes: Fakes, kind: str) -> None:
    fakes.wire_into(c)
    await hold(c, who.home, who.alana, kind)


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_her_read_is_answered_with_the_stored_secret(db_url: str, people: People, fakes: Fakes, kind: str) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await setup(c, people, fakes, kind)
            await her_read(people, kind)
            assert fakes.count(kind) >= 1 and fakes.secrets() == {SECRETS[kind]}

    go(scenario())


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_a_successful_read_moves_checked_at_forward_each_time(db_url: str, people: People, fakes: Fakes,
                                                              kind: str) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await setup(c, people, fakes, kind)
            who = owner(kind, people.alana)
            was = age(db_url, people.home, kind, who)
            await her_read(people, kind)
            first = stored_at(db_url, people.home, kind, who)
            assert first > was
            await her_read(people, kind)
            assert stored_at(db_url, people.home, kind, who) > first

    go(scenario())


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_a_read_moves_only_the_connection_it_was_made_with(db_url: str, people: People, fakes: Fakes, kind: str) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await setup(c, people, fakes, kind)
            held = [(people.home, people.alana, k) for k in KIND_NAMES if k != kind]
            held += [(people.other, people.kim, kind)]
            if kind_named(kind).default_holder == "person":
                held += [(people.home, people.sam, kind)]
            for household, person, k in held:
                await hold(c, household, person, k)
            before = {key: age(db_url, key[0], key[2], owner(key[2], key[1])) for key in held}
            target = age(db_url, people.home, kind, owner(kind, people.alana))
            await her_read(people, kind)
            assert stored_at(db_url, people.home, kind, owner(kind, people.alana)) > target
            for key, was in before.items():
                assert stored_at(db_url, key[0], key[2], owner(key[2], key[1])) == was, key

    go(scenario())


@pytest.mark.parametrize("failure", ["refuse", "down", "html"])
@pytest.mark.parametrize("kind", KIND_NAMES)
def test_a_read_the_service_did_not_answer_leaves_checked_at(db_url: str, people: People, fakes: Fakes, kind: str,
                                                             failure: str) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await setup(c, people, fakes, kind)
            who = owner(kind, people.alana)
            was = age(db_url, people.home, kind, who)
            fakes.mode[kind] = failure
            with pytest.raises(Exception):
                await her_read(people, kind)
            assert fakes.count(kind) >= 1
            assert stored_at(db_url, people.home, kind, who) == was

    go(scenario())

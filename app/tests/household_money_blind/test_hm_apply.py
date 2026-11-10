"""How a money fact is stored: the household's (`members`, no owner) unless its owner said who may know; health stays
private to its owner."""

import pytest
from ashley.memory.model import Add, Kind
from contract.conversations_support import run
from hm_support import AT, Home, make_home, memory, money


async def stored(home: Home, *ops: Add) -> tuple[int, ...]:
    async with memory(home.url) as mem:
        return await mem.apply(home.id, home.talk, ops, AT)


def test_finance_not_stated_is_stored_as_members_with_no_owner_and_keeps_who_it_is_about(db_url: str) -> None:
    home = make_home(db_url)
    [about_alana, about_house, sharedly] = run_apply(home, money(home.alana, home.alana, "private"),
                                                    money(None, home.alana, "private"),
                                                    money(home.elodie, home.elodie, "shared"))
    assert home.row(about_alana) == (home.alana, None, "members", "finance")
    assert home.row(about_house) == (None, None, "members", "finance")
    assert home.row(sharedly) == (home.elodie, None, "members", "finance")


def test_finance_the_owner_stated_private_keeps_the_owner_and_private(db_url: str) -> None:
    home = make_home(db_url)
    [kept] = run_apply(home, money(home.alana, home.alana, "private", stated=True))
    assert home.row(kept) == (home.alana, home.alana, "private", "finance")


def test_finance_the_owner_stated_you_can_tell_is_not_forced_to_members(db_url: str) -> None:
    home = make_home(db_url)
    [told] = run_apply(home, money(home.alana, home.alana, "discreet", stated=True))
    assert home.row(told)[2] == "discreet" and home.row(told)[1] == home.alana


def test_health_stays_pinned_private_to_its_owner(db_url: str) -> None:
    home = make_home(db_url)
    [pinned, stated] = run_apply(home, money(home.alana, home.alana, "shared", kind="health", text="Alana has a cold"),
                                 money(home.alana, home.alana, "private", stated=True, kind="health", text="Alana is sick"))
    assert home.row(pinned) == (home.alana, home.alana, "private", "health")
    assert home.row(stated) == (home.alana, home.alana, "private", "health")


@pytest.mark.parametrize("kind", ["preference", "routine", "plan", "home"])
def test_other_kinds_are_not_turned_into_members(db_url: str, kind: Kind) -> None:
    home = make_home(db_url)
    [one] = run_apply(home, money(home.alana, home.alana, "shared", kind=kind, text="Alana likes tea"))
    assert home.row(one)[2:] == ("shared", kind) and home.row(one)[1] == home.alana


def run_apply(home: Home, *ops: Add) -> tuple[int, ...]:
    got: list[tuple[int, ...]] = []

    async def go() -> None:
        got.append(await stored(home, *ops))

    run(go())
    return got[0]

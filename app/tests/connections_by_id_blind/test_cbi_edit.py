"""`Connections.replace`, `relabel`, `remove` and `opened` by id: what each changes, what it keeps, and who can reach
a connection. A connection a person cannot see is None/False and nothing is written."""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
from ashley.connections.connections import Connections, LabelTaken
from connections_by_id_blind_support import People, add, age, connections, go, rows, snapshot

NEW_URL = "https://elsewhere.test"


def _recent(moment: datetime) -> bool:
    return abs((datetime.now(UTC) - moment).total_seconds()) < 60


# --- replace ---------------------------------------------------------------------------------------------------------


def test_replace_gives_a_new_address_and_secret_and_keeps_id_and_label(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            i = await add(c, people.home, people.alana, "multi", "work", secret="old")
            await add(c, people.home, people.alana, "multi", "other", secret="untouched")
            got = await c.replace(i, people.home, people.alana, NEW_URL, "new")
            assert got is not None and (got.id, got.label, got.base_url, got.kind) == (i, "work", NEW_URL, "multi")
            opened = await c.opened(i, people.home, people.alana)
            assert opened is not None and opened.secret == "new" and opened.connection == got
            rest = [x for x in await c.of_household(people.home, people.alana) if x.id != i]
            assert [(x.label, x.base_url) for x in rest] == [("other", "https://music.test")]
            assert rows(db_url) == 2

    go(scenario())


def test_replace_moves_added_at_and_checked_at_to_now_and_names_who_replaced_it(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            i = await add(c, people.home, people.alana, "multi", "work")
            aged_added, aged_checked = age(db_url, i)
            got = await c.replace(i, people.home, people.sam, NEW_URL, "new")
            assert got is not None and got.added_by == people.sam
            assert got.added_at > aged_added and got.checked_at > aged_checked
            assert _recent(got.added_at) and _recent(got.checked_at)
            again = (await c.of_household(people.home, people.sam))[0]
            assert again == got

    go(scenario())


def test_a_replaced_secret_still_opens_under_its_owner(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            household = await add(c, people.home, people.alana, "multi", "a")
            own = await add(c, people.home, people.alana, "own", "a")
            assert await c.replace(household, people.home, people.sam, NEW_URL, "h2") is not None
            assert await c.replace(own, people.home, people.alana, NEW_URL, "p2") is not None
            for i, who, secret in ((household, None, "h2"), (own, people.alana, "p2")):
                opened = await c.opened(i, people.home, who)
                assert opened is not None and opened.secret == secret

    go(scenario())


# --- relabel ---------------------------------------------------------------------------------------------------------


def test_relabel_changes_the_label_alone_and_checked_at_does_not_move(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            i = await add(c, people.home, people.alana, "multi", "work", secret="kept")
            aged_added, aged_checked = age(db_url, i)
            before = snapshot(db_url)
            got = await c.relabel(i, people.home, people.sam, "laptop")
            assert got is not None and got.label == "laptop" and got.id == i
            assert (got.added_at, got.checked_at, got.added_by, got.base_url) == (
                aged_added, aged_checked, people.alana, "https://music.test")
            opened = await c.opened(i, people.home)
            assert opened is not None and opened.secret == "kept" and opened.connection == got
            after = snapshot(db_url)
            assert [r[:4] + r[5:] for r in after] == [r[:4] + r[5:] for r in before]

    go(scenario())


def test_relabel_to_the_empty_label_when_free(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            i = await add(c, people.home, people.alana, "multi", "work")
            got = await c.relabel(i, people.home, people.alana, "")
            assert got is not None and got.label == ""

    go(scenario())


def test_relabel_to_a_label_a_sibling_has_is_taken_and_changes_nothing(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await add(c, people.home, people.alana, "multi", "taken")
            i = await add(c, people.home, people.alana, "multi", "mine")
            before = snapshot(db_url)
            with pytest.raises(LabelTaken) as raised:
                await c.relabel(i, people.home, people.alana, "taken")
            assert raised.value.kind == "multi"
            assert snapshot(db_url) == before

    go(scenario())


def test_relabel_is_exact_about_case_and_whitespace(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await add(c, people.home, people.alana, "multi", "taken")
            i = await add(c, people.home, people.alana, "multi", "mine")
            got = await c.relabel(i, people.home, people.alana, "Taken")
            assert got is not None and got.label == "Taken"
            got = await c.relabel(i, people.home, people.alana, "taken ")
            assert got is not None and got.label == "taken "

    go(scenario())


def test_relabel_may_reuse_a_label_another_owner_or_kind_has(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await add(c, people.home, people.sam, "own", "x")
            await add(c, people.home, people.alana, "big", "x")
            i = await add(c, people.home, people.alana, "own", "mine")
            got = await c.relabel(i, people.home, people.alana, "x")
            assert got is not None and got.label == "x"

    go(scenario())


# --- remove and opened -----------------------------------------------------------------------------------------------


def test_remove_deletes_that_one_connection_alone(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            a = await add(c, people.home, people.alana, "multi", "a")
            b = await add(c, people.home, people.alana, "multi", "b")
            assert await c.remove(a, people.home, people.sam) is True
            assert await c.opened(a, people.home) is None
            assert await c.opened(b, people.home) is not None
            assert await c.remove(a, people.home, people.sam) is False
            assert rows(db_url) == 1

    go(scenario())


def test_remove_logs_the_removal(db_url: str, people: People, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    async def scenario() -> None:
        async with connections(db_url) as c:
            await c.remove(await add(c, people.home, people.alana, "multi", "a"), people.home, people.alana)

    go(scenario())
    assert any("connections.removed" in r.getMessage() for r in caplog.records)


def test_opened_by_an_id_nothing_has_is_none(db_url: str, people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            await add(c, people.home, people.alana, "multi", "a")
            assert await c.opened(10**7, people.home) is None
            assert await c.replace(10**7, people.home, people.alana, NEW_URL, "k") is None
            assert await c.relabel(10**7, people.home, people.alana, "z") is None
            assert await c.remove(10**7, people.home, people.alana) is False

    go(scenario())


# --- visibility: one table for every operation --------------------------------------------------------------------------

def person(p: int | None) -> int:
    assert p is not None
    return p


Op = Callable[[Connections, int, int, int | None], Awaitable[object]]
OPS: dict[str, tuple[Op, object]] = {
    "opened": (lambda c, i, h, p: c.opened(i, h, p), None),
    "replace": (lambda c, i, h, p: c.replace(i, h, person(p), NEW_URL, "intruder"), None),
    "relabel": (lambda c, i, h, p: c.relabel(i, h, person(p), "intruder"), None),
    "remove": (lambda c, i, h, p: c.remove(i, h, p), False),
}


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("case", ["personal_by_housemate", "household_from_other_household",
                                  "personal_from_other_household"])
def test_a_connection_a_person_cannot_see_is_none_or_false_and_nothing_is_written(db_url: str, people: People,
                                                                                 op: str, case: str) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            household = await add(c, people.home, people.alana, "multi", "h")
            personal = await add(c, people.home, people.alana, "own", "p")
            await add(c, people.other, people.kim, "multi", "k")
            target, household_id, who = {
                "personal_by_housemate": (personal, people.home, people.sam),
                "household_from_other_household": (household, people.other, people.kim),
                "personal_from_other_household": (personal, people.other, people.kim)}[case]
            before = snapshot(db_url)
            got = await OPS[op][0](c, target, household_id, who)
            assert got is OPS[op][1]
            assert snapshot(db_url) == before

    go(scenario())


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("case", ["household_by_member", "household_by_other_member", "personal_by_owner"])
def test_a_connection_a_person_can_see_is_reached(db_url: str, people: People, op: str, case: str) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            household = await add(c, people.home, people.alana, "multi", "h")
            personal = await add(c, people.home, people.alana, "own", "p")
            target, who = {"household_by_member": (household, people.alana),
                           "household_by_other_member": (household, people.sam),
                           "personal_by_owner": (personal, people.alana)}[case]
            got = await OPS[op][0](c, target, people.home, who)
            assert got is not None and got is not False

    go(scenario())


def test_opened_without_a_person_reaches_the_households_connection_and_not_a_persons_own(db_url: str,
                                                                                         people: People) -> None:
    async def scenario() -> None:
        async with connections(db_url) as c:
            household = await add(c, people.home, people.alana, "multi", "h")
            personal = await add(c, people.home, people.alana, "own", "p")
            assert await c.opened(household, people.home) is not None
            assert await c.opened(household, people.home, None) is not None
            assert await c.opened(personal, people.home) is None
            assert await c.opened(personal, people.home, None) is None

    go(scenario())

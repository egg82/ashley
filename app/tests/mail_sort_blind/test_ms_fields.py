"""A watch keeps `brief` and `standing` as armed, shows them as stored, and arming the same target again replaces both."""

from mail_sort_blind_support import BRIEF, Store, scenario


def test_a_watch_stores_the_brief_and_the_standing_flag_it_was_armed_with(db_url: str) -> None:
    async def body(s: Store) -> None:
        a = await s.armed(brief=BRIEF, standing=True)
        got = await s.store.get(a)
        assert got is not None
        assert (got.brief, got.standing) == (BRIEF, True)
        [live] = await s.store.live(s.household_id, s.person_id)
        assert (live.brief, live.standing) == (BRIEF, True)

    scenario(db_url, body)


def test_a_watch_armed_with_neither_has_no_brief_and_is_not_standing(db_url: str) -> None:
    async def body(s: Store) -> None:
        got = await s.store.get(await s.armed())
        assert got is not None
        assert (got.brief, got.standing) == (None, False)

    scenario(db_url, body)


def test_arming_again_replaces_the_brief_and_the_standing_flag(db_url: str) -> None:
    async def body(s: Store) -> None:
        a = await s.armed(brief=BRIEF, standing=True)
        assert (await s.arm_for(brief="a new brief zs-9921", standing=False)).id == a
        got = await s.store.get(a)
        assert got is not None and (got.brief, got.standing) == ("a new brief zs-9921", False)
        assert (await s.arm_for(standing=True)).id == a
        again = await s.store.get(a)
        assert again is not None and (again.brief, again.standing) == (None, True)

    scenario(db_url, body)

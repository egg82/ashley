"""untold and told: what the asker may hear of what she did, oldest first, until it is told."""

from errands_blind_support import World, age_told, done_id, done_result, row, scenario, seconds_since, told, untold


def test_untold_gives_the_askers_finished_errands_oldest_first(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.finished("first")
        b = await w.finished("second")
        c = await w.finished("third")
        assert await untold(w.errands, w.asker) == [a, b, c]

    scenario(db_url, body)


def test_untold_carries_the_result(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.finished("I put cat litter on the list.")
        [done] = await w.errands.untold(w.asker, 10)
        assert done_result(done) == "I put cat litter on the list."

    scenario(db_url, body)


def test_untold_honours_the_limit_keeping_the_oldest(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = [await w.finished(f"errand {i}") for i in range(5)]
        assert [d for d in await untold(w.errands, w.asker, 2)] == ids[:2]
        assert await untold(w.errands, w.asker, 5) == ids
        assert await untold(w.errands, w.asker, 50) == ids

    scenario(db_url, body)


def test_untold_gives_only_errands_that_are_done(db_url: str) -> None:
    async def body(w: World) -> None:
        running, _ = await w.owed_claimed()
        refused, refused_attempt = await w.owed_claimed()
        await w.errands.give_up(refused, refused_attempt, "refused")
        done = await w.finished("did it")
        due = await w.owe()
        assert row(w.url, due)["state"] == "due" and row(w.url, running)["state"] == "running"
        assert await untold(w.errands, w.asker) == [done]

    scenario(db_url, body)


def test_the_asker_hears_a_private_result_as_well_as_a_shared_one(db_url: str) -> None:
    async def body(w: World) -> None:
        shared = await w.finished("shared one", "shared")
        private = await w.finished("private one", "private")
        assert await untold(w.errands, w.asker) == [shared, private]

    scenario(db_url, body)


def test_someone_else_in_the_household_does_not_hear_the_askers_errands(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.finished("shared one", "shared")
        await w.finished("private one", "private")
        assert await untold(w.errands, w.mate) == []

    scenario(db_url, body)


def test_a_person_of_another_household_hears_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.finished("shared one", "shared")
        assert await untold(w.errands, w.other_person) == []

    scenario(db_url, body)


def test_untold_does_not_mark_anything_told(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.finished("did it")
        assert await untold(w.errands, w.asker) == [eid]
        assert await untold(w.errands, w.asker) == [eid]
        assert row(w.url, eid)["told_at"] is None

    scenario(db_url, body)


def test_told_stops_an_errand_coming_back(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.finished("first")
        b = await w.finished("second")
        await told(w.errands, a)
        assert await untold(w.errands, w.asker) == [b]
        assert row(w.url, a)["told_at"] is not None
        assert row(w.url, b)["told_at"] is None

    scenario(db_url, body)


def test_told_marks_every_id_it_is_given_and_no_other(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = [await w.finished(f"errand {i}", "private" if i % 2 else "shared") for i in range(4)]
        await told(w.errands, ids[0], ids[1], ids[2])
        assert await untold(w.errands, w.asker) == [ids[3]]
        await told(w.errands, ids[3])
        assert await untold(w.errands, w.asker) == []

    scenario(db_url, body)


def test_told_with_nothing_changes_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.finished("did it")
        await told(w.errands)
        assert await untold(w.errands, w.asker) == [eid]

    scenario(db_url, body)


def test_told_leaves_the_outcome_as_it_was(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.finished("did it")
        before = row(w.url, eid)
        await told(w.errands, eid)
        after = row(w.url, eid)
        assert {k: v for k, v in after.items() if k != "told_at"} == {k: v for k, v in before.items() if k != "told_at"}

    scenario(db_url, body)


def test_a_reply_others_may_hear_withholds_private_results_and_keeps_shared_ones(db_url: str) -> None:
    async def body(w: World) -> None:
        shared = await w.finished("shared one", "shared")
        await w.finished("private one", "private")
        heard = await w.errands.untold(w.asker, 10, owner_only=False)
        assert [done_id(d) for d in heard] == [shared]

    scenario(db_url, body)


def test_told_again_keeps_the_first_time_it_was_told(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.finished("did it")
        await told(w.errands, eid)
        age_told(w.url, eid, 5_000)
        await told(w.errands, eid)
        assert seconds_since(w.url, eid, "told_at") > 4_000

    scenario(db_url, body)

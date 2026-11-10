"""What each outcome of a run does to the errand: finish, release, give_up; and what ends the tick."""

from dataclasses import replace

from ashley.inference.inference import InferenceRefused, InferenceUnavailable
from job_blind_support import (CONF, GOOD, HOUSE, RESULT_TEXT, World, fact_count, owed_again, row, scenario,
                               set_attempts)


def test_a_plain_reply_finishes_the_errand_with_its_text(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        await w.tick()
        r = row(w.url, eid)
        assert r["state"] == "done" and r["result"] == RESULT_TEXT and r["finished_at"] is not None
        assert w.errands.named("finish") == [(eid, 1, RESULT_TEXT)]
        assert w.errands.named("release") == [] and w.errands.named("give_up") == []

    scenario(db_url, body)


def test_the_result_is_the_reply_text_not_the_spoken_line(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        await w.tick()
        assert row(w.url, eid)["result"] == GOOD.text != GOOD.spoken

    scenario(db_url, body)


def test_finish_is_called_at_the_attempt_the_claim_gave(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        set_attempts(w.url, eid, 1)
        await w.tick()
        assert w.errands.named("finish") == [(eid, 2, RESULT_TEXT)]

    scenario(db_url, body)


def test_the_result_keeps_the_asks_visibility(db_url: str) -> None:
    async def body(w: World) -> None:
        shared = await w.owe(visibility="shared")
        private = await w.owe(visibility="private")
        await w.tick()
        assert (row(w.url, shared)["visibility"], row(w.url, private)["visibility"]) == ("shared", "private")
        assert w.states(shared, private) == ["done", "done"]

    scenario(db_url, body)


def test_the_outcome_is_not_stored_as_a_fact(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.owe()
        before = fact_count(w.url)
        await w.tick()
        assert fact_count(w.url) == before

    scenario(db_url, body)


def test_a_reply_with_owed_set_releases_the_errand(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        w.model.play(owed_again(HOUSE))
        await w.tick()
        r = row(w.url, eid)
        assert r["state"] == "due" and r["attempts"] == 1 and r["result"] is None
        assert w.errands.named("release") == [(eid, 1, CONF.max_attempts)]
        assert w.errands.named("finish") == [] and w.errands.named("give_up") == []

    scenario(db_url, body)


def test_a_reply_with_owed_set_is_not_finished_even_with_text(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        w.model.play(owed_again())
        await w.tick()
        assert row(w.url, eid)["result"] is None and row(w.url, eid)["state"] != "done"

    scenario(db_url, body)


def test_a_release_at_max_attempts_gives_up_for_attempts(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        set_attempts(w.url, eid, CONF.max_attempts - 1)
        w.model.play(owed_again())
        await w.tick()
        r = row(w.url, eid)
        assert r["state"] == "given_up" and r["reason"] == "attempts"
        assert w.errands.named("release") == [(eid, CONF.max_attempts, CONF.max_attempts)]

    scenario(db_url, body)


def test_max_attempts_comes_from_the_config(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        w.model.play(owed_again())
        await w.tick()
        assert row(w.url, eid)["state"] == "given_up"
        assert w.errands.named("release")[0][2] == 1

    scenario(db_url, body, replace(CONF, max_attempts=1))


def test_inference_unavailable_releases_the_errand(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        w.model.play(InferenceUnavailable("down"))
        await w.tick()
        r = row(w.url, eid)
        assert r["state"] == "due" and r["attempts"] == 1 and r["result"] is None
        assert w.errands.named("release") == [(eid, 1, CONF.max_attempts)]
        assert w.errands.named("finish") == [] and w.errands.named("give_up") == []

    scenario(db_url, body)


def test_inference_unavailable_ends_the_tick(db_url: str) -> None:
    async def body(w: World) -> None:
        first, second = await w.owe_many(2)
        w.model.play(InferenceUnavailable("down"))
        await w.tick()
        assert len(w.model.prompts) == 1
        assert w.states(first, second) == ["due", "due"]
        assert row(w.url, second)["attempts"] == 0

    scenario(db_url, body)


def test_the_next_tick_after_inference_comes_back_runs_the_errand(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        w.model.play(InferenceUnavailable("down"))
        await w.tick()
        await w.tick()
        r = row(w.url, eid)
        assert r["state"] == "done" and r["attempts"] == 2

    scenario(db_url, body)


def test_inference_unavailable_at_the_last_attempt_gives_up_for_attempts(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        set_attempts(w.url, eid, CONF.max_attempts - 1)
        w.model.play(InferenceUnavailable("down"))
        await w.tick()
        r = row(w.url, eid)
        assert r["state"] == "given_up" and r["reason"] == "attempts"

    scenario(db_url, body)


def test_a_tick_that_ended_on_unavailable_still_swept(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.owe()
        w.model.play(InferenceUnavailable("down"))
        await w.tick()
        await w.tick()
        assert len(w.errands.named("sweep")) == 2

    scenario(db_url, body)


def test_a_refusal_gives_the_errand_up_as_refused(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        w.model.play(InferenceRefused("no"))
        await w.tick()
        r = row(w.url, eid)
        assert r["state"] == "given_up" and r["reason"] == "refused" and r["result"] is None
        assert w.errands.named("give_up") == [(eid, 1, "refused")]
        assert w.errands.named("release") == [] and w.errands.named("finish") == []

    scenario(db_url, body)


def test_a_refused_errand_is_not_retried_by_the_next_tick(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        w.model.play(InferenceRefused("no"))
        await w.tick()
        await w.tick()
        assert len(w.model.prompts) == 1 and row(w.url, eid)["attempts"] == 1

    scenario(db_url, body)


def test_a_refusal_does_not_end_the_tick(db_url: str) -> None:
    async def body(w: World) -> None:
        refused, fine = await w.owe_many(2)
        w.model.play(InferenceRefused("no"), GOOD)
        await w.tick()
        assert w.states(refused, fine) == ["given_up", "done"]

    scenario(db_url, body)


def test_each_errand_in_a_batch_gets_its_own_outcome(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.owe()
        b = await w.owe("search")
        w.model.play(owed_again(), GOOD)
        await w.tick()
        assert w.states(a, b) == ["due", "done"]

    scenario(db_url, body)

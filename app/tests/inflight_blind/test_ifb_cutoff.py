"""A step cut off at the token limit is asked again to act small once per turn, and the count is saved with the turn's
work in Postgres: a runner that resumes it does not ask again, and its next cut-off closes the turn as too big."""

from ashley.channels import resume, unsaid
from ashley.inference.inference import InferenceCutOff, InferenceUnavailable
from contract.conversations_support import run
from ifb_resume_support import DONE, world


def test_a_resumed_turn_that_was_cut_off_is_asked_to_act_small_and_finishes(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan()
            w.model.script = [InferenceCutOff("cut off"), DONE]
            assert await resume.sweep() == 1
            assert await w.r.hers() == [DONE.text]
            assert [p.messages[-1] for p in w.model.prompts][1] == unsaid.TOO_BIG

    run(go())


def test_the_count_survives_the_runner_that_asked(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan()
            w.model.script = [InferenceCutOff("cut off"), InferenceUnavailable("down")]
            await resume.sweep()
            assert len(w.model.prompts) == 2 and await w.r.hers() == [] and await w.r.rows() == 1
            await w.r.expire_all()
            w.model.prompts.clear()
            w.model.script = [InferenceCutOff("cut off again")]
            await resume.sweep()
            assert len(w.model.prompts) == 1 and await w.r.rows() == 0

    run(go())

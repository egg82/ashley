"""Resuming work whose runner stopped, blind: `sweep` takes up each orphan once, from its checkpoint, and the person
gets one stored reply; a change that began without a result is never run again."""

import asyncio
from collections.abc import Callable

import pytest
from ashley import logs, services
from ashley.channels import resume, unsaid
from ashley.channels.checkpoint import INTERRUPTED
from ashley.conversations.inflight import Claim, InFlight, InFlightUnavailable, Orphan
from ashley.conversations.model import AgreedOutcome, NewTurn, Turn
from ashley.inference.inference import InferenceUnavailable
from ashley.inference.model import ToolCall, ToolCalls, ToolResult
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from contract.contract_support import unreachable_conninfo
from contract.conversations_support import POLICY, events, run
from ifb_resume_support import DONE, SYSTEM, asking, results_sent, world


def test_a_turn_with_nothing_asked_yet_is_answered_and_stored_once(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            claim = await w.orphan()
            w.model.script = [DONE]
            assert await resume.sweep() == 1
            assert await w.r.hers() == [DONE.text]
            conv = await w.r.conversations.get(claim.conversation_id)
            assert conv is not None and conv.turns[-1].text == DONE.text and conv.turns[-1].author == "ashley"
            assert await w.r.rows() == 0
            assert await resume.sweep() == 0
            assert await w.r.hers() == [DONE.text]

    run(go())


def test_nothing_is_resumed_while_a_claim_is_fresh(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.r.begin("anything")
            assert await resume.sweep() == 0
            assert w.model.prompts == [] and await w.r.hers() == [] and await w.r.rows() == 1

    run(go())


def test_a_read_with_no_result_is_run_again_and_its_result_reaches_the_model(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan(asking(("c1", "look")))
            w.model.script = [DONE]
            assert await resume.sweep() == 1
            assert [c.id for c in w.tools.ran] == ["c1"]
            [prompt] = w.model.prompts
            assert results_sent(prompt)["c1"].content == '{"ran": "look"}'

    run(go())


def test_a_change_started_with_no_result_is_never_run_and_she_is_told_it_may_have_happened(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan(asking(("c1", "switch")), started=frozenset({"c1"}))
            w.model.script = [DONE]
            assert await resume.sweep() == 1
            assert w.tools.ran == []
            [prompt] = w.model.prompts
            assert results_sent(prompt)["c1"] == ToolResult("c1", INTERRUPTED, is_error=True)
            assert await w.r.hers() == [DONE.text]

    run(go())


def test_a_change_with_its_result_is_not_run_again_and_its_result_is_kept(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            done = {"c1": ToolResult("c1", '{"on": true}')}
            await w.orphan(asking(("c1", "switch"), done=done), started=frozenset({"c1"}))
            w.model.script = [DONE]
            assert await resume.sweep() == 1
            assert w.tools.ran == []
            assert results_sent(w.model.prompts[0])["c1"] == done["c1"]

    run(go())


def test_a_round_with_a_read_to_redo_and_a_change_lost_runs_only_the_read(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan(asking(("c1", "look"), ("c2", "switch"), ("c3", "look")), started=frozenset({"c2"}))
            w.model.script = [DONE]
            await resume.sweep()
            assert sorted(c.id for c in w.tools.ran) == ["c1", "c3"]
            sent = results_sent(w.model.prompts[0])
            assert set(sent) == {"c1", "c2", "c3"} and sent["c2"].is_error

    run(go())


def test_the_model_is_sent_the_checkpoints_system_prompt_not_a_rebuilt_one(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan()
            w.model.script = [DONE]
            await resume.sweep()
            assert w.model.prompts[0].system["default"] == SYSTEM

    run(go())


def test_the_model_is_sent_what_the_person_said(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan(text="dim the hallway")
            w.model.script = [DONE]
            await resume.sweep()
            assert "dim the hallway" in repr(w.model.prompts[0].messages)

    run(go())


def test_the_resumed_turn_can_ask_for_more_tools_and_still_ends_in_one_reply(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan(asking(("c1", "look")))
            w.model.script = [ToolCalls((ToolCall("c9", "look", {}),)), DONE]
            assert await resume.sweep() == 1
            assert [c.id for c in w.tools.ran] == ["c1", "c9"]
            assert await w.r.hers() == [DONE.text]

    run(go())


def test_two_sweeps_at_once_give_one_reply(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan()
            w.model.script = [DONE, DONE]
            counts = await asyncio.gather(resume.sweep(), resume.sweep())
            assert sum(counts) == 1
            assert await w.r.hers() == [DONE.text]

    run(go())


def test_a_sweep_takes_at_most_a_batch_and_the_next_takes_the_rest(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            for i in range(25):
                await w.orphan(thread=f"web:{i}")
            w.model.script = [DONE] * 25
            first = await resume.sweep()
            assert 0 < first < 25
            total = first
            for _ in range(5):
                total += await resume.sweep()
            assert total == 25 and len(await w.r.hers()) == 25

    run(go())


def test_a_third_runner_resumes_the_turn_and_a_fourth_gives_it_up(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with world(db_url) as w:
            claim = await w.orphan()
            [second] = await w.r.inflight.orphaned(10)      # a second runner took it and stopped
            await w.r.expire(second.claim)
            w.model.script = [DONE]
            capsys.readouterr()
            assert await resume.sweep() == 1                # the third
            assert await w.r.hers() == [DONE.text]
            assert events(capsys.readouterr().out, "respond.failed") == []

            gone = await w.orphan(thread="web:2")
            for _ in range(2):
                [again] = await w.r.inflight.orphaned(10)
                await w.r.expire(again.claim)
            w.model.script = [DONE]
            before = len(w.model.prompts)
            await resume.sweep()                            # would be the fourth
            assert len(w.model.prompts) == before
            assert await w.r.hers() == [DONE.text]
            failed = events(capsys.readouterr().out, "respond.failed")
            assert [f.get("reason") for f in failed] == ["gave_up"] and failed[0].get("resumed") == "true"
            await w.r.expire_all()
            assert await resume.sweep() == 0                # given up for good, not taken up again
            del claim, gone

    run(go())


@pytest.mark.parametrize("raw", ["not json at all", "{}", "[]", "null", '{"inbound": 1}'])
def test_a_checkpoint_that_cannot_be_read_stores_no_reply_and_the_sweep_goes_on(
        db_url: str, capsys: pytest.CaptureFixture[str], raw: str) -> None:
    logs.setup()

    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan(raw=raw, thread="web:bad")
            await w.orphan(thread="web:good")
            w.model.script = [DONE]
            capsys.readouterr()
            await resume.sweep()
            assert await w.r.hers() == [DONE.text]
            assert len(w.model.prompts) == 1
            failed = events(capsys.readouterr().out, "respond.failed")
            assert [f.get("reason") for f in failed] == ["bad_checkpoint"]
            await w.r.expire_all()
            assert await resume.sweep() == 0                # unreadable work is not taken up again

    run(go())


def test_a_resumed_turn_whose_model_cannot_be_reached_says_so_once_and_keeps_its_work(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan(later_by="outbox")
            w.model.script = [InferenceUnavailable("down")]
            capsys.readouterr()
            await resume.sweep()
            assert await w.r.hers() == [unsaid.UNREACHABLE]
            failed = events(capsys.readouterr().out, "respond.failed")
            assert len(failed) == 1 and failed[0].get("resumed") == "true"

    run(go())


def test_the_log_says_the_turn_was_taken_up_and_answered_and_never_what_was_said(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    secret = "zqPLANTED4417"  # gitleaks:allow (test fixture)

    async def go() -> None:
        async with world(db_url) as w:
            claim = await w.orphan(text=f"my code is {secret}")
            w.model.script = [DONE]
            capsys.readouterr()
            await resume.sweep()
            out = capsys.readouterr().out
            [taken] = events(out, "respond.resumed")
            assert {str(claim.conversation_id), str(claim.said_id), "2"} <= set(taken.values())
            [done] = events(out, "respond.done")
            assert done.get("resumed") == "true"
            assert secret not in out and DONE.text not in out

    run(go())


class Flaky(InFlight):
    """The real InFlight, except `orphaned` cannot reach the database the first `failures` times."""

    def __init__(self, real: InFlight, failures: int) -> None:
        self.real, self.failures = real, failures

    @property
    def claim_s(self) -> float:
        return self.real.claim_s

    async def begin(self, conversation_id: int, said_id: int, checkpoint: str) -> Claim:
        return await self.real.begin(conversation_id, said_id, checkpoint)

    async def save(self, claim: Claim, checkpoint: str) -> None:
        return await self.real.save(claim, checkpoint)

    async def renew(self, claim: Claim) -> None:
        return await self.real.renew(claim)

    async def said(self, claim: Claim, turn: NewTurn) -> Turn:
        return await self.real.said(claim, turn)

    async def finish(self, claim: Claim, turn: NewTurn, after: Callable[[Turn], str] | None = None) -> Turn:
        return await self.real.finish(claim, turn, after)

    async def agreed(self, claim: Claim, outcome: AgreedOutcome) -> None:
        await self.real.agreed(claim, outcome)

    async def drop(self, claim: Claim) -> bool:
        return await self.real.drop(claim)

    async def orphaned(self, limit: int) -> list[Orphan]:
        if self.failures:
            self.failures -= 1
            raise InFlightUnavailable("down")
        return await self.real.orphaned(limit)

    async def working(self, conversation_id: int) -> frozenset[int]:
        return await self.real.working(conversation_id)


class Sleeps:
    """A `sleep` for `run` that counts and cancels after `limit`."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        if len(self.delays) >= self.limit:
            raise asyncio.CancelledError


def test_run_sweeps_then_sleeps_a_positive_poll_until_cancelled(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan()
            w.model.script = [DONE]
            sleeps = Sleeps(3)
            with pytest.raises(asyncio.CancelledError):
                await resume.run(sleeps)
            assert await w.r.hers() == [DONE.text]
            assert len(sleeps.delays) == 3 and all(d > 0 for d in sleeps.delays)

    run(go())


def test_run_survives_an_unreachable_database_logs_it_once_and_resumes_after(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with world(db_url) as w:
            flaky = Flaky(w.r.inflight, failures=3)
            services.register(InFlight, flaky)
            await w.orphan()
            w.model.script = [DONE]
            capsys.readouterr()
            with pytest.raises(asyncio.CancelledError):
                await resume.run(Sleeps(6))
            assert await w.r.hers() == [DONE.text]
            assert len(events(capsys.readouterr().out, "inflight.unavailable")) == 1

    run(go())


def test_sweep_raises_unavailable_when_the_database_cannot_be_reached() -> None:

    async def go() -> None:
        db = PoolDatabase(unreachable_conninfo(), connect_timeout_s=0.1)
        await db.open()
        services.register(InFlight, PostgresInFlight(db, POLICY, 15.0))
        try:
            with pytest.raises(InFlightUnavailable):
                await resume.sweep()
        finally:
            services.unregister(InFlight)
            await db.close()

    run(go())


def test_a_checkpoint_that_cannot_be_read_on_the_last_allowed_runner_is_bad_not_given_up(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with world(db_url) as w:
            await w.orphan(raw="not json")
            [second] = await w.r.inflight.orphaned(10)
            await w.r.expire(second.claim)
            capsys.readouterr()
            await resume.sweep()                            # the third runner
            failed = events(capsys.readouterr().out, "respond.failed")
            assert [f.get("reason") for f in failed] == ["bad_checkpoint"]

    run(go())

"""The memory write job over real Postgres, with a scripted writer and a stand-in lease: what it picks, what it marks,
what stops a tick, the failure cap, and losing the lease."""

import asyncio
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from ashley import logs, services
from ashley.conversations.conversations import Conversations
from ashley.conversations.model import Conversation
from ashley.inference.inference import InferenceRejected, InferenceUnavailable
from ashley.memory.memory import FactWriter, Memory
from ashley.memory.model import Add, Fact, Invalidate, NewFact, Op
from ashley.memory.postgres import PostgresMemory
from ashley.memory.write_job import Policy, WriteJob
from ashley.referee.lease import Body, Lease, NullLease

from conversations_support import POLICY, events, household, make, place_before_now, run, scalar
from memory_support import conversation, pool, say

AT = datetime(2026, 3, 1, tzinfo=UTC)
JOB = Policy(tick_s=0.01, batch=10, candidates=10, max_failures=2, embed_batch=10)
IDLE = POLICY.timings["chat"].idle_after_s + 1


def learned(conversation_id: int, text: str = "") -> Add:
    return Add(NewFact(None, None, "shared", False, "home", False, text or f"Learned in {conversation_id}"))


class ScriptedWriter(FactWriter):
    """Answers `script[conversation id]` (ops, or an exception to raise), else one fact named for the conversation.
    Records every call."""

    def __init__(self, script: dict[int, tuple[Op, ...] | Exception] | None = None) -> None:
        self.script = script or {}
        self.calls: list[tuple[Conversation, tuple[int, ...]]] = []

    async def decide(self, conversation: Conversation, known: Sequence[Fact], now: datetime) -> tuple[Op, ...]:
        self.calls.append((conversation, tuple(f.id for f in known)))
        answer = self.script.get(conversation.id, (learned(conversation.id),))
        if isinstance(answer, Exception):
            raise answer
        return answer

    def asked(self) -> list[int]:
        return [c.id for c, _ in self.calls]


@asynccontextmanager
async def wired(url: str) -> AsyncGenerator[None]:
    async with pool(url) as db:
        services.register(Memory, PostgresMemory(db))
        services.register(Conversations, make(db))
        try:
            yield
        finally:
            services.unregister(Memory)
            services.unregister(Conversations)


def idle_talk(url: str, home: int, *turns: str) -> int:
    talk = conversation(url, home)
    say(url, talk, *turns)
    place_before_now(url, talk, IDLE)
    return talk


def watermark(url: str, talk: int) -> object:
    return scalar(url, "SELECT coalesce((SELECT written_turn_id FROM memory_writes WHERE conversation_id = %s), -1)",
                  (talk,))


def facts_from(url: str, talk: int) -> int:
    return int(scalar(url, "SELECT count(*) FROM facts WHERE source_conversation_id = %s", (talk,)))


def test_idle_conversations_are_written_once_and_again_only_for_new_turns(db_url: str) -> None:
    home = household(db_url)
    first, second = idle_talk(db_url, home, "Mochi eats at six", "Noted"), idle_talk(db_url, home, "The boiler is new")
    still_open = conversation(db_url, home)
    say(db_url, still_open, "Hello")
    writer = ScriptedWriter({first: (learned(first, "Mochi eats at six"),)})

    async def scenario() -> None:
        async with wired(db_url):
            job = WriteJob(writer, JOB, POLICY, lambda: AT)
            assert (await job.tick())["written"] == 2
            assert writer.asked() == [first, second], "oldest first, the open one left alone"
            assert (facts_from(db_url, first), facts_from(db_url, second), facts_from(db_url, still_open)) == (1, 1, 0)
            assert await job.tick() == {}, "nothing is written twice"
            (new_turn, reply) = say(db_url, first, "Mochi now eats at seven", "Noted")
            place_before_now(db_url, first, IDLE)
            assert (await job.tick())["written"] == 1
            again, known = writer.calls[-1]
            assert [t.id for t in again.turns] == [new_turn, reply], "only the turns after the watermark"
            assert len(known) == 1, "the fact written last time is a candidate"
            assert watermark(db_url, first) == reply

    run(scenario())


def household_says(url: str, talk: int, text: str) -> int:
    return int(scalar(url, "INSERT INTO turns (conversation_id, household_id, author, text) "
                           "SELECT id, household_id, 'household', %s FROM conversations WHERE id = %s RETURNING id",
                      (text, talk)))


def test_a_turn_of_the_household_is_never_shown_to_the_writer_and_alone_is_not_written(db_url: str) -> None:
    home = household(db_url)
    mixed = idle_talk(db_url, home, "Mochi eats at six", "Noted")
    household_says(db_url, mixed, "event alana_arrived; about Alana")
    only_household = conversation(db_url, home)
    household_says(db_url, only_household, "event alana_arrived; about Alana")
    place_before_now(db_url, only_household, IDLE)
    place_before_now(db_url, mixed, IDLE)
    writer = ScriptedWriter()

    async def scenario() -> None:
        async with wired(db_url):
            job = WriteJob(writer, JOB, POLICY, lambda: AT)
            assert (await job.tick())["written"] == 1
            assert writer.asked() == [mixed]
            assert {t.author for t in writer.calls[0][0].turns} == {"person", "ashley"}

    run(scenario())


def test_inference_unavailable_ends_the_tick_and_marks_nothing(db_url: str) -> None:
    home = household(db_url)
    first, second = idle_talk(db_url, home, "Mochi eats at six"), idle_talk(db_url, home, "The boiler is new")
    writer = ScriptedWriter({first: InferenceUnavailable("haiku is down")})

    async def scenario() -> None:
        async with wired(db_url):
            job = WriteJob(writer, JOB, POLICY, lambda: AT)
            assert await job.tick() == {}
            assert writer.asked() == [first], "the rest of the batch waits for the next tick"
            assert (watermark(db_url, first), watermark(db_url, second)) == (-1, -1)
            assert scalar(db_url, "SELECT count(*) FROM memory_writes") == 0, "no failure is recorded either"
            writer.script.clear()
            assert (await job.tick())["written"] == 2

    run(scenario())


def test_a_rejected_write_is_a_failure_of_that_conversation_and_is_held_back_after_the_cap(db_url: str) -> None:
    home = household(db_url)
    bad, fine = idle_talk(db_url, home, "Forget the kiln"), idle_talk(db_url, home, "The boiler is new")
    writer = ScriptedWriter({bad: InferenceRejected("every route rejected the request")})

    async def scenario() -> None:
        async with wired(db_url):
            job = WriteJob(writer, JOB, POLICY, lambda: AT)
            first = await job.tick()
            assert (first["failed"], first["written"]) == (1, 1), "the rest of the batch is still written"
            assert (await job.tick())["failed"] == 1
            assert await job.tick() == {}, "two failures in a row hold it back"
            assert writer.asked() == [bad, fine, bad]

    run(scenario())


def test_a_refused_write_moves_on_and_is_held_back_after_the_cap(db_url: str) -> None:
    home = household(db_url)
    stale, fine = idle_talk(db_url, home, "Forget the kiln"), idle_talk(db_url, home, "The boiler is new")
    writer = ScriptedWriter({stale: (learned(stale), Invalidate(999_999))})

    async def scenario() -> None:
        async with wired(db_url):
            job = WriteJob(writer, JOB, POLICY, lambda: AT)
            first = await job.tick()
            assert (first["failed"], first["written"]) == (1, 1), "the next conversation is still written"
            assert (facts_from(db_url, stale), watermark(db_url, stale)) == (0, -1)
            assert (await job.tick())["failed"] == 1
            assert await job.tick() == {}, "two failures in a row hold it back"
            assert writer.asked() == [stale, fine, stale]
            say(db_url, stale, "Really, forget it")
            place_before_now(db_url, stale, IDLE)
            writer.script.clear()
            assert (await job.tick())["written"] == 1

    run(scenario())


def test_an_unexpected_error_fails_that_conversation_alone_and_logs_its_type_not_its_message(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    broken, fine = idle_talk(db_url, home, "Mochi eats at six"), idle_talk(db_url, home, "The boiler is new")
    writer = ScriptedWriter({broken: RuntimeError("Elodie's therapist is on Tuesdays")})
    logs.setup({"LOG_LEVEL": "info"})

    async def scenario() -> None:
        async with wired(db_url):
            job = WriteJob(writer, JOB, POLICY, lambda: AT)
            counts = await job.tick()
            assert (counts["failed"], counts["written"]) == (1, 1), "the next conversation is still written"
            assert (facts_from(db_url, broken), watermark(db_url, broken), facts_from(db_url, fine)) == (0, -1, 1)
            await job.tick()
            assert await job.tick() == {}, "it counts toward the same cap"
            assert writer.asked() == [broken, fine, broken]

    capsys.readouterr()
    run(scenario())
    out = capsys.readouterr().out
    first, _ = events(out, "memory.job.failed")
    assert (first["level"], first["conversation"], first["error"], first["exc"]) == (
        "error", str(broken), "RuntimeError", "RuntimeError")
    assert "write_job.py" in first["tb"] and "Tuesdays" not in out and "therapist" not in out


def test_a_watermark_moved_under_the_job_skips_rather_than_writes_twice(db_url: str) -> None:
    home = household(db_url)
    talk = idle_talk(db_url, home, "Mochi eats at six")

    class RacedWriter(ScriptedWriter):
        async def decide(self, conversation: Conversation, known: Sequence[Fact], now: datetime) -> tuple[Op, ...]:
            scalar(db_url, "INSERT INTO memory_writes (conversation_id, household_id, written_turn_id) "
                           "VALUES (%s, %s, %s) RETURNING 1", (talk, home, conversation.turns[-1].id))
            return await super().decide(conversation, known, now)

    async def scenario() -> None:
        async with wired(db_url):
            assert (await WriteJob(RacedWriter(), JOB, POLICY, lambda: AT).tick())["skipped"] == 1
            assert facts_from(db_url, talk) == 0

    run(scenario())


def test_a_watermark_moved_short_of_the_job_still_skips(db_url: str) -> None:
    home = household(db_url)
    talk = idle_talk(db_url, home, "Mochi eats at six", "and sleeps at ten")
    first = int(scalar(db_url, "SELECT min(id) FROM turns WHERE conversation_id = %s", (talk,)))

    class RacedWriter(ScriptedWriter):
        async def decide(self, conversation: Conversation, known: Sequence[Fact], now: datetime) -> tuple[Op, ...]:
            scalar(db_url, "INSERT INTO memory_writes (conversation_id, household_id, written_turn_id) "
                           "VALUES (%s, %s, %s) RETURNING 1", (talk, home, first))
            return await super().decide(conversation, known, now)

    async def scenario() -> None:
        async with wired(db_url):
            assert (await WriteJob(RacedWriter(), JOB, POLICY, lambda: AT).tick())["skipped"] == 1
            assert facts_from(db_url, talk) == 0
            assert watermark(db_url, talk) == first

    run(scenario())


class LostAfter(Lease):
    """Runs the body until `lost` is set, then cancels it, as a lease lost in etcd does."""

    def __init__(self) -> None:
        self.lost = asyncio.Event()

    async def run(self, name: str, body: Body) -> None:
        task = asyncio.ensure_future(body())
        await self.lost.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_losing_the_lease_stops_the_job_and_leaves_the_conversation_it_was_on_unwritten(db_url: str) -> None:
    home = household(db_url)
    first, second, third = (idle_talk(db_url, home, text) for text in ("Mochi eats at six", "The boiler", "A kiln"))
    lease = LostAfter()

    class SlowSecond(ScriptedWriter):
        async def decide(self, conversation: Conversation, known: Sequence[Fact], now: datetime) -> tuple[Op, ...]:
            ops = await super().decide(conversation, known, now)
            if conversation.id == second:
                lease.lost.set()
                await asyncio.Event().wait()
            return ops

    writer = SlowSecond()

    async def scenario() -> None:
        async with wired(db_url):
            await lease.run("memory-write", WriteJob(writer, JOB, POLICY, lambda: AT).run)
            assert writer.asked() == [first, second]
            assert [facts_from(db_url, t) for t in (first, second, third)] == [1, 0, 0]
            assert [watermark(db_url, t) != -1 for t in (first, second, third)] == [True, False, False]

    run(scenario())


def test_the_null_lease_never_runs_the_job() -> None:
    writer = ScriptedWriter()

    async def scenario() -> None:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(NullLease().run("memory-write", WriteJob(writer, JOB, POLICY).run), 0.05)
        assert writer.calls == []

    run(scenario())


def test_log_lines_carry_ids_and_counts_never_text(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    secret = "Elodie's therapist is on Tuesdays"
    talk = idle_talk(db_url, home, secret)
    writer = ScriptedWriter({talk: (learned(talk, secret),)})
    logs.setup({"LOG_LEVEL": "info"})

    async def scenario() -> None:
        async with wired(db_url):
            await WriteJob(writer, JOB, POLICY, lambda: AT).tick()

    capsys.readouterr()
    run(scenario())
    out = capsys.readouterr().out
    (tick,) = events(out, "memory.job.tick")
    assert {k: tick[k] for k in ("batch", "written", "skipped", "failed")} == {
        "batch": "1", "written": "1", "skipped": "0", "failed": "0"}
    assert "duration_ms" in tick and "stopped" not in tick
    (written,) = events(out, "memory.job.written")
    fact_id = scalar(db_url, "SELECT id FROM facts")
    assert (written["conversation"], written["add"], written["inserted"]) == (str(talk), "1", str(fact_id))
    assert "Tuesdays" not in out and "therapist" not in out

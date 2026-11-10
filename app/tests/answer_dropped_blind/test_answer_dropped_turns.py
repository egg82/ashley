"""Web chat turns over Postgres: a held line and a closing step that says nothing, the prod case (six tool rounds,
then the closing step under tool choice none), a turn resumed by another runner, and a conversation that refuses her
turn. The person is never left with only the held line, and an empty turn is never stored."""

import asyncio
from collections.abc import Callable
from dataclasses import replace

import pytest
from ashley import logs, services
from ashley.channels import resume
from ashley.channels import respond as respond_module
from ashley.channels.respond import RespondUnavailable, respond
from ashley.conversations.conversations import ConversationClosed
from ashley.conversations.inflight import Claim, InFlight, Orphan
from ashley.conversations.model import AgreedOutcome, NewTurn, Turn
from ashley.inference.model import ToolCalls
from ashley.inference.reply import Reply
from contract.conversations_support import events, run, scalar
from answer_dropped_blind_support import (CHECKING, EMPTY, GOOD, HANG, LINE, SAID_ONLY, WRITTEN_ONLY, Hang, SECOND, SENTINEL, BLANK, World, database,
                                          ended, kill_the_turn, settled, switch_on)


def with_rounds(monkeypatch: pytest.MonkeyPatch, rounds: int) -> None:
    monkeypatch.setitem(respond_module.LIMITS, "chat",
                        replace(respond_module.LIMITS["chat"], max_tool_rounds=rounds, escalates=False))


ROUNDS = pytest.mark.parametrize("rounds", [1, 6])


def held_script(rounds: int, *closing: ToolCalls | Reply | Hang) -> list[ToolCalls | Reply | Hang]:
    return [CHECKING, *[switch_on(f"c{i}") for i in range(rounds)], *closing]


@ROUNDS
def test_a_held_turn_whose_closing_step_is_empty_once_is_asked_again(
        world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], rounds: int) -> None:
    logs.setup()
    with_rounds(monkeypatch, rounds)
    world.first.model.play(*held_script(rounds, EMPTY, GOOD))

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            out = await respond(world.inbound())
            assert out.follows
            await settled(world, 2)

    run(go())
    out = capsys.readouterr().out
    assert world.hers() == [(CHECKING.text, True), (GOOD.text, False)]
    assert len(world.first.tools.ran) == rounds and world.first.model.choices[-2:] == ["none", "none"]
    assert world.work() == 0
    assert len(events(out, "respond.reply_empty")) == 1 and events(out, "respond.failed") == []


@ROUNDS
def test_the_prod_case_a_held_turn_whose_closing_step_stays_empty_ends_with_no_line_of_hers(
        world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], rounds: int) -> None:
    logs.setup()
    with_rounds(monkeypatch, rounds)
    world.first.model.play(*held_script(rounds, EMPTY, BLANK))

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            await respond(world.inbound())
            await ended(world)
            await asyncio.sleep(0.3)

    run(go())
    out = capsys.readouterr().out
    assert world.hers() == [(CHECKING.text, True)]
    assert world.work() == 0 and world.first.model.steps == rounds + 3
    assert [e["reason"] for e in events(out, "respond.failed")] == ["unworded"]


def test_a_first_reply_that_is_empty_twice_stores_no_line_of_hers_on_a_page(world: World) -> None:
    world.first.model.play(EMPTY, EMPTY)

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            with pytest.raises(RespondUnavailable):
                await respond(world.inbound())
            await asyncio.sleep(0.2)

    run(go())
    assert world.hers() == [] and world.work() == 0


def test_a_first_reply_that_is_empty_twice_says_the_line_when_it_is_said_aloud(world: World) -> None:
    world.first.model.play(EMPTY, EMPTY)

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            out = await respond(world.inbound(medium="spoken"))
            assert (out.body, out.follows) == (LINE, False)
            await asyncio.sleep(0.2)

    run(go())
    assert world.hers() == [(LINE, False)] and world.work() == 0


def test_a_first_reply_that_is_empty_once_is_asked_again(world: World) -> None:
    world.first.model.play(EMPTY, GOOD)

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            out = await respond(world.inbound())
            assert (out.body, out.follows) == (GOOD.text, False)
            await asyncio.sleep(0.2)

    run(go())
    assert world.hers() == [(GOOD.text, False)] and world.first.model.steps == 2


@pytest.mark.parametrize("rounds", [1, 6])
@pytest.mark.parametrize(("closing", "answer"), [([EMPTY, EMPTY], None), ([EMPTY, SECOND], SECOND.text), ([GOOD], GOOD.text)],
                         ids=["line", "retried", "plain"])
def test_a_turn_resumed_by_another_pod_at_its_last_round_ends_as_a_first_runner_would(
        world: World, monkeypatch: pytest.MonkeyPatch, rounds: int, closing: list[ToolCalls | Reply | Hang], answer: str | None) -> None:
    """The first pod dies in the closing step (after `rounds` tool rounds, the last one the limit when it is 1); the
    second finishes the turn and the held line is not stored again; a closing step empty twice ends with no line of
    hers on a page (`answer` None)."""
    with_rounds(monkeypatch, rounds)
    world.first.model.play(*held_script(rounds, HANG))
    world.second.model.play(*closing)

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            await respond(world.inbound())
            await asyncio.wait_for(world.first.model.asked.wait(), 5)
            assert kill_the_turn() >= 1
            await asyncio.sleep(0.45)
            world.as_pod(world.second)
            assert await resume.sweep() == 1
            assert await resume.sweep() == 0

    run(go())
    assert world.hers() == [(CHECKING.text, True), *([] if answer is None else [(answer, False)])]
    assert len(world.first.tools.ran) == rounds and world.second.tools.ran == []
    assert world.work() == 0


class Refusing(InFlight):
    """The real store, except that finishing the turn is refused with `error`."""

    def __init__(self, real: InFlight, error: Exception) -> None:
        self.real = real
        self.error = error

    @property
    def claim_s(self) -> float:
        return self.real.claim_s

    async def begin(self, conversation_id: int, said_id: int, checkpoint: str) -> Claim:
        return await self.real.begin(conversation_id, said_id, checkpoint)

    async def save(self, claim: Claim, checkpoint: str) -> None:
        await self.real.save(claim, checkpoint)

    async def renew(self, claim: Claim) -> None:
        await self.real.renew(claim)

    async def said(self, claim: Claim, turn: NewTurn) -> Turn:
        return await self.real.said(claim, turn)

    async def finish(self, claim: Claim, turn: NewTurn, after: Callable[[Turn], str] | None = None) -> Turn:
        raise self.error

    async def agreed(self, claim: Claim, outcome: AgreedOutcome) -> None:
        raise self.error

    async def drop(self, claim: Claim) -> bool:
        return await self.real.drop(claim)

    async def orphaned(self, limit: int) -> list[Orphan]:
        return await self.real.orphaned(limit)

    async def working(self, conversation_id: int) -> frozenset[int]:
        return await self.real.working(conversation_id)


@pytest.mark.parametrize("script", [[GOOD], [EMPTY, GOOD]], ids=["reply", "retried"])
def test_a_closed_conversation_still_fails_as_unstorable_with_its_cause(
        world: World, capsys: pytest.CaptureFixture[str], script: list[ToolCalls | Reply | Hang]) -> None:
    logs.setup()
    world.first.model.play(*script)
    raised: list[BaseException] = []

    async def go() -> None:
        async with database(world):
            services.register(InFlight, Refusing(services.get(InFlight), ConversationClosed(1)))
            world.as_pod(world.first)
            try:
                await respond(world.inbound(f"turn on the lamp {SENTINEL}"))
            except Exception as error:
                raised.append(error)
            await asyncio.sleep(0.3)

    run(go())
    seen = capsys.readouterr()
    failed = events(seen.out, "respond.failed")
    assert raised and not isinstance(raised[0], AssertionError)
    assert [e["reason"] for e in failed] == ["unstorable"]
    assert failed[0]["cause"] == "ConversationClosed" and failed[0].get("check", "") == ""
    assert world.hers() == [] and scalar(world.url, "SELECT count(*) FROM turn_work") == 0
    assert SENTINEL not in seen.out + seen.err and GOOD.text not in seen.out + seen.err


def test_a_turn_the_conversation_does_not_store_logs_its_class_and_fixed_phrase(
        world: World, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    world.first.model.play(GOOD)

    async def go() -> None:
        async with database(world):
            services.register(InFlight, Refusing(services.get(InFlight), ValueError("a turn has text")))
            world.as_pod(world.first)
            try:
                await respond(world.inbound())
            except Exception:
                pass
            await asyncio.sleep(0.3)

    run(go())
    failed = events(capsys.readouterr().out, "respond.failed")
    assert [e["reason"] for e in failed] == ["unstorable"]
    assert failed[0]["cause"] == "ValueError" and failed[0]["check"] == "a turn has text"
    assert world.hers() == []


@pytest.mark.parametrize(("closing", "answer"), [([WRITTEN_ONLY, SAID_ONLY], SAID_ONLY.spoken), ([WRITTEN_ONLY, WRITTEN_ONLY], LINE)],
                         ids=["retried", "line"])
def test_a_held_spoken_turn_judges_its_replies_by_what_is_said(world: World, closing: list[Reply], answer: str) -> None:
    world.first.model.play(*held_script(1, *closing))

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            await respond(world.inbound(medium="spoken"))
            await settled(world, 2)

    run(go())
    assert world.hers() == [(CHECKING.spoken, True), (answer, False)]


@pytest.mark.parametrize(("closing", "answer"), [([WRITTEN_ONLY, SAID_ONLY], SAID_ONLY.spoken), ([WRITTEN_ONLY, WRITTEN_ONLY], LINE)],
                         ids=["retried", "line"])
def test_a_spoken_turn_resumed_by_another_pod_judges_its_replies_by_what_is_said(
        world: World, closing: list[Reply], answer: str) -> None:
    world.first.model.play(*held_script(1, HANG))
    world.second.model.play(*closing)

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            await respond(world.inbound(medium="spoken"))
            await asyncio.wait_for(world.first.model.asked.wait(), 5)
            assert kill_the_turn() >= 1
            await asyncio.sleep(0.45)
            world.as_pod(world.second)
            assert await resume.sweep() == 1

    run(go())
    assert world.hers() == [(CHECKING.spoken, True), (answer, False)]


@pytest.mark.parametrize("script", [[GOOD], [EMPTY, GOOD]], ids=["reply", "retried"])
def test_a_held_turns_refused_answer_logs_the_cause_and_no_content(
        world: World, capsys: pytest.CaptureFixture[str], script: list[Reply]) -> None:
    logs.setup()
    world.first.model.play(CHECKING, *script)

    async def go() -> None:
        async with database(world):
            services.register(InFlight, Refusing(services.get(InFlight), ConversationClosed(1)))
            world.as_pod(world.first)
            await respond(world.inbound(f"turn on the lamp {SENTINEL}"))
            await asyncio.sleep(0.5)

    run(go())
    seen = capsys.readouterr()
    failed = events(seen.out, "respond.failed")
    assert [e["reason"] for e in failed] == ["unstorable"]
    assert failed[0]["cause"] == "ConversationClosed" and failed[0].get("check", "") == ""
    assert world.hers() == [(CHECKING.text, True)] and world.work() == 0
    assert SENTINEL not in seen.out + seen.err and GOOD.text not in seen.out + seen.err

"""A move to spam or trash after outside words (`ashley.tools.mail_vet.not_junk`), through `Outside` over the real Gmail
adapter and a fake Gmail: it goes to the judge only when every message carries a label Gmail itself put on it (`SPAM`,
`CATEGORY_PROMOTIONS`), and is held as `not_junk` with no judge call otherwise. The labels are read from the provider, so
a message that only says so in its subject changes nothing."""

import logging
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from ashley import services
from ashley.connections.resources import Use
from ashley.inference.model import ToolCall
from ashley.senses.proposals import Proposals
from ashley.tools.action_judge import ActionJudge, Verdict, View
from ashley.tools.mail import MailTools
from ashley.tools.outside import Outside, Standing
from ashley.tools.outside_config import load
from mail_gmail_support import ALANA, HOME, FakeGmail, connect, message, wire
from outside_ask_support import CONVERSATION, TURN, Memory, run

MILLIS = 1_762_000_000_000
STANDING = Standing(HOME, ALANA, private=True, agreeing=True)
CONFIG = load()
PAT = "Pat <pat@school.test>"
MAIL = [message("j1", "Sale", MILLIS, ("SPAM",)), message("j2", "Deals", MILLIS, ("INBOX", "CATEGORY_PROMOTIONS")),
        message("k1", "Field trip", MILLIS, ("INBOX",)), message("k2", "SPAM CATEGORY_PROMOTIONS", MILLIS, ("INBOX",))]
SUBJECTS = {"j1": "Sale", "j2": "Deals", "k1": "Field trip", "k2": "SPAM CATEGORY_PROMOTIONS"}


@dataclass
class Spy(ActionJudge):
    answer: str = "run"
    asked: list[tuple[Sequence[str], View]] = field(default_factory=list[tuple[Sequence[str], View]])

    async def decide(self, words: Sequence[str], view: View) -> Verdict:
        self.asked.append((words, view))
        return Verdict("run" if self.answer == "run" else "ask", "asked_directly", "You asked for it.")


@dataclass
class Case:
    outside: Outside
    gmail: FakeGmail
    spy: Spy
    memory: Memory

    async def move(self, folder: str, *ids: str) -> str:
        await self.outside.catalogue()
        entries = [{"id": i, "from": PAT, "subject": SUBJECTS[i]} for i in ids]
        return (await self.outside.call(ToolCall("c1", "mail_label", {"messages": entries, "folder": folder}))).content

    def moved(self) -> bool:
        return any(path == "/messages/batchModify" for path, _ in self.gmail.posted)

    def held(self) -> list[Any]:
        return [c for p in self.memory.rows.values() for c in p.payload.calls]


@pytest.fixture(autouse=True)
def judge_unwired() -> Generator[None]:
    yield
    services.unregister(ActionJudge)
    services.unregister(Proposals)


def case(answer: str = "run") -> Case:
    gmail = FakeGmail([dict(m) for m in MAIL])
    wire(gmail)
    connect()
    memory, spy = Memory(), Spy(answer)
    services.register(Proposals, memory)
    services.register(ActionJudge, spy)

    async def said() -> Sequence[str]:
        return ("clear out the junk",)

    outside = Outside(MailTools(Use(HOME, ALANA, True), 8000), STANDING, (CONVERSATION, TURN), tainted="mail_read", words=said)
    return Case(outside, gmail, spy, memory)


def events(caplog: pytest.LogCaptureFixture, event: str) -> list[Mapping[str, object]]:
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == event]


@pytest.mark.parametrize("folder", ["spam", "trash"])
def test_every_target_labelled_by_gmail_goes_to_the_judge_and_runs_on_its_word(folder: str) -> None:
    async def go() -> None:
        c = case()
        await c.move(folder, "j1", "j2")
        assert len(c.spy.asked) == 1 and c.moved() and c.held() == []

    run(go())


def test_one_unlabelled_target_holds_the_whole_move_with_its_reason_and_no_judge_call(caplog: pytest.LogCaptureFixture) -> None:
    async def go() -> None:
        caplog.set_level(logging.INFO)
        c = case()
        got = await c.move("trash", "j1", "k1")
        assert c.spy.asked == [] and not c.moved()
        [held] = c.held()
        assert held.tool == "mail_label" and held.explanation == CONFIG.not_junk and CONFIG.not_junk in got
        [line] = events(caplog, "outside.judged")
        assert (line["decision"], line["reason"], line["tool"]) == ("ask", "not_junk", "mail_label")

    run(go())


def test_a_subject_that_names_the_labels_is_not_the_label() -> None:
    async def go() -> None:
        c = case()
        await c.move("spam", "k2")
        assert c.spy.asked == [] and not c.moved() and len(c.held()) == 1

    run(go())


def test_a_message_gmail_cannot_find_is_held() -> None:
    async def go() -> None:
        c = case()
        c.gmail.gone.add("j2")
        await c.move("trash", "j1", "j2")
        assert c.spy.asked == [] and not c.moved() and len(c.held()) == 1

    run(go())


def test_a_judge_that_asks_still_holds_a_labelled_move() -> None:
    async def go() -> None:
        c = case("ask")
        await c.move("spam", "j1")
        assert len(c.spy.asked) == 1 and not c.moved() and len(c.held()) == 1

    run(go())


def test_an_archive_is_judged_whatever_labels_the_message_has() -> None:
    async def go() -> None:
        c = case()
        await c.move("archive", "k1")
        assert len(c.spy.asked) == 1 and c.moved()

    run(go())

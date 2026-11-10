"""The recipient check of `mail_send` (`ashley.tools.mail_vet`), through `Outside` over the real Gmail adapter and a fake
Gmail: a recipient that is a household address, one the mailbox sent to before, or one the person's words contain goes on
to the judge; any other is held as `recipient_unknown` with no judge call, and the held call carries the reason's words."""

import copy
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
BODY = "PLANTED body the judge must only see the length of"


@dataclass
class Spy(ActionJudge):
    asked: list[tuple[Sequence[str], View]] = field(default_factory=list[tuple[Sequence[str], View]])

    async def decide(self, words: Sequence[str], view: View) -> Verdict:
        self.asked.append((words, view))
        return Verdict("run", "asked_directly", "You asked for it.")


@dataclass
class Case:
    outside: Outside
    call: ToolCall
    gmail: FakeGmail
    spy: Spy
    memory: Memory

    async def go(self) -> str:
        await self.outside.catalogue()
        return (await self.outside.call(self.call)).content

    def sent(self) -> bool:
        return any(path == "/messages/send" for path, _ in self.gmail.posted)

    def held(self) -> list[Any]:
        return [c for p in self.memory.rows.values() for c in p.payload.calls]


@pytest.fixture(autouse=True)
def judge_unwired() -> Generator[None]:
    yield
    services.unregister(ActionJudge)
    services.unregister(Proposals)


def events(caplog: pytest.LogCaptureFixture, event: str) -> list[Mapping[str, object]]:
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == event]


def sent_to(address: str) -> dict[str, Any]:
    found = copy.deepcopy(message("s1", "Earlier", MILLIS, ("SENT",)))
    for header in found["payload"]["headers"]:
        if header["name"] == "To":
            header["value"] = address
    return found


def case(*to: str, words: Sequence[str] = ("please send it",), before: Sequence[str] = (), cc: Sequence[str] = ()) -> Case:
    gmail = FakeGmail([sent_to(a) for a in before])
    wire(gmail)
    connect()
    memory, spy = Memory(), Spy()
    services.register(Proposals, memory)
    services.register(ActionJudge, spy)

    async def said() -> Sequence[str]:
        return words

    outside = Outside(MailTools(Use(HOME, ALANA, True), 8000), STANDING, (CONVERSATION, TURN), tainted="mail_read", words=said)
    call = ToolCall("c1", "mail_send", {"to": list(to), "cc": list(cc), "subject": "Hi", "body": BODY})
    return Case(outside, call, gmail, spy, memory)


def test_a_household_address_goes_to_the_judge_and_the_body_is_only_a_length() -> None:
    async def go() -> None:
        c = case("alana@gmail.test", words=("send myself the notes",))
        got = await c.go()
        assert c.sent() and "sent" in got
        [(words, view)] = c.spy.asked
        assert words == ("send myself the notes",)
        assert view.fields["to"] == "alana@gmail.test" and view.fields["body"] == f"<text, {len(BODY)} chars>"
        assert "PLANTED" not in repr(view)

    run(go())


def test_an_address_the_mailbox_sent_to_before_goes_to_the_judge_after_one_sent_folder_query() -> None:
    async def go() -> None:
        c = case("pat@school.test", before=("pat@school.test",))
        await c.go()
        assert len(c.spy.asked) == 1 and c.sent()
        queries = [q["q"][0] for path, q, _ in c.gmail.seen if path == "/messages" and "q" in q]
        assert len(queries) == 1 and "in:sent" in queries[0] and "to:(pat@school.test)" in queries[0]

    run(go())


def test_an_address_in_the_person_s_words_is_known_whatever_its_case_and_a_trailing_full_stop() -> None:
    async def go() -> None:
        c = case("bob@x.test", words=("email Bob@X.test.",))
        await c.go()
        assert len(c.spy.asked) == 1 and c.sent()
        assert [p for p, _, _ in c.gmail.seen if p == "/messages"] == [], "known by the words: no sent-folder query"

    run(go())


@pytest.mark.parametrize("words", [("email bobby@x.test",), ("email notbob@x.test",), ("email bob",)])
def test_an_address_that_only_contains_or_resembles_one_in_the_words_is_not_known(words: tuple[str, ...]) -> None:
    async def go() -> None:
        c = case("bob@x.test", words=words)
        await c.go()
        assert c.spy.asked == [] and not c.sent()

    run(go())


def test_an_unknown_recipient_is_held_with_its_reason_and_no_judge_call(caplog: pytest.LogCaptureFixture) -> None:
    async def go() -> None:
        caplog.set_level(logging.INFO)
        c = case("stranger@evil.test", before=("pat@school.test",))
        got = await c.go()
        assert c.spy.asked == [] and not c.sent()
        [held] = c.held()
        assert held.tool == "mail_send" and held.explanation == CONFIG.unknown_recipient
        assert CONFIG.unknown_recipient in got
        [line] = events(caplog, "outside.judged")
        assert (line["decision"], line["reason"], line["tool"]) == ("ask", "recipient_unknown", "mail_send")
        logged = repr([r.__dict__ for r in caplog.records if r.name == "ashley.tools"])
        assert "stranger@evil.test" not in logged and CONFIG.unknown_recipient not in logged

    run(go())


def test_one_unknown_recipient_among_known_ones_holds_the_whole_send() -> None:
    async def go() -> None:
        c = case("alana@gmail.test", "stranger@evil.test")
        await c.go()
        assert c.spy.asked == [] and not c.sent() and len(c.held()) == 1

    run(go())


def test_an_unknown_cc_holds_the_send_too() -> None:
    async def go() -> None:
        c = case("alana@gmail.test", cc=("stranger@evil.test",))
        await c.go()
        assert c.spy.asked == [] and not c.sent()

    run(go())


def test_a_sent_folder_that_cannot_be_read_counts_as_not_known() -> None:
    async def go() -> None:
        c = case("pat@school.test", before=("pat@school.test",))
        c.gmail.down = 503
        await c.go()
        assert c.spy.asked == [] and not c.sent()

    run(go())


def test_no_words_of_the_person_s_means_no_judge_call_and_a_hold() -> None:
    async def go() -> None:
        c = case("alana@gmail.test", words=())
        got = await c.go()
        assert c.spy.asked == [] and not c.sent() and CONFIG.no_words in got
        assert [h.explanation for h in c.held()] == [CONFIG.no_words]

    run(go())

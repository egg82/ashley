"""A carried answer of hers comes with a compact form of the code runs its question asked for: language, outcome, the
script and what it printed cut to the kind's budgets, and the names of the files it made. One read per reply; a
reply whose runs cannot be read goes on without them."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from ashley import logs, services
from ashley.channels import respond as respond_module
from ashley.channels.history_runs import carried
from ashley.channels.respond import respond
from ashley.conversations.model import Turn
from ashley.inference.model import Message
from ashley.inference.reply import Reply
from ashley.runs.model import Artifact, NewRun, Output, Run
from ashley.runs.runs import Runs, RunsUnavailable
from contract.conversations_support import events
from respond_support import Fakes, inbound, wired as wired

AT = datetime(2026, 10, 30, tzinfo=UTC)
REPLY = Reply(spoken="It printed 3.", text="It printed 3.")
SECRET = "zq-run-secret"


class Book(Runs):
    def __init__(self) -> None:
        self.runs: list[Run] = []
        self.down = False
        self.asked: list[tuple[int, tuple[int, ...], int]] = []

    async def start(self, run: NewRun) -> int:
        raise NotImplementedError

    async def finish(self, run_id: int, output: Output, artifacts: Sequence[Artifact] = ()) -> Run:
        raise NotImplementedError

    async def get(self, household_id: int, run_id: int) -> Run | None:
        raise NotImplementedError

    async def in_conversation(self, household_id: int, conversation_id: int) -> list[Run]:
        raise NotImplementedError

    async def last_on_bench(self, household_id: int, bench_id: int) -> Mapping[int, Run]:
        raise NotImplementedError

    async def files_left(self, household_id: int, bench_id: int, piece_id: int) -> Mapping[str, str]:
        raise NotImplementedError

    async def of_turns(self, household_id: int, turn_ids: tuple[int, ...], latest: int) -> list[Run]:
        if self.down:
            raise RunsUnavailable("down")
        self.asked.append((household_id, turn_ids, latest))
        found = [r for r in self.runs if r.household_id == household_id and r.turn_id in turn_ids]
        return found[len(found) - latest:] if latest else []


def run(id: int, turn: int, script: str = "print(1 + 2)", output: Output | None = Output("ran", 0, "3\n", "")) -> Run:
    return Run(id, 10, 1, turn, f"c{id}", "python", script, "", {}, AT, None if output is None else AT, output)


@pytest.fixture
def book(wired: Fakes) -> Book:
    made = Book()
    services.register(Runs, made)
    return made


def earlier(wired: Fakes) -> Message:
    """Her answer, as the second message's prompt carried it."""
    message = wired.inference.prompts[-1].messages[1]
    assert isinstance(message, Message)
    return message


def ask_twice(wired: Fakes) -> None:
    """Two messages on one thread; the first's person turn is 100 and her answer 101."""
    wired.inference.script = [REPLY, REPLY]
    asyncio.run(respond(inbound("add one and two", kind="chat")))
    asyncio.run(respond(inbound("what did it print", kind="chat")))


def test_her_carried_answer_comes_with_its_run(wired: Fakes, book: Book) -> None:
    book.runs.append(run(1, 100, output=Output("ran", 0, "3\n", "", files={"out.csv": "a,b"})))
    ask_twice(wired)
    message = earlier(wired)
    assert message.author == "ashley"
    assert message.text.startswith("(Sat 24 Oct 2026 18:00) It printed 3.\n")
    assert "python" in message.text and "ran, exit 0" in message.text
    assert "print(1 + 2)" in message.text and "3\n" in message.text and "out.csv" in message.text
    assert "a,b" not in message.text


def test_the_runs_are_read_once_for_the_person_turns_carried(wired: Fakes, book: Book) -> None:
    ask_twice(wired)
    assert book.asked == [(10, (100,), respond_module.LIMITS["chat"].carried_runs)]


def test_the_script_and_output_are_cut_to_the_kinds_budgets(wired: Fakes, book: Book,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(respond_module.LIMITS, "chat",
                        replace(respond_module.LIMITS["chat"], run_script_chars=10, run_output_chars=5))
    book.runs.append(run(1, 100, script="x = 1\n" * 50, output=Output("ran", 0, "0123456789", "")))
    ask_twice(wired)
    content = earlier(wired).text
    assert "x = 1\nx = 1" not in content and "x = 1" in content
    assert "56789" in content and "01234" not in content


def test_a_failed_run_says_how_it_ended(wired: Fakes, book: Book) -> None:
    book.runs.append(run(1, 100, output=Output("timed_out", None, "", "Traceback")))
    ask_twice(wired)
    assert "timed_out" in earlier(wired).text
    assert "Traceback" in earlier(wired).text


def test_a_run_with_no_recorded_result_says_so(wired: Fakes, book: Book) -> None:
    book.runs.append(run(1, 100, output=None))
    ask_twice(wired)
    assert "no result" in earlier(wired).text


def test_unreadable_runs_leave_the_reply_going_and_are_logged_without_content(
        wired: Fakes, book: Book, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    book.down = True
    book.runs.append(run(1, 100, script=SECRET))
    ask_twice(wired)
    assert earlier(wired).text == "(Sat 24 Oct 2026 18:00) It printed 3."
    out = capsys.readouterr().out
    assert events(out, "respond.runs_unavailable") and SECRET not in out


def test_an_answer_the_hearer_may_not_hear_leaves_its_runs_under_no_earlier_answer(book: Book) -> None:
    def turn(id: int, author: str, answers: int | None = None) -> Turn:
        return Turn(id, "ashley" if author == "ashley" else "person", None, "t", AT, answers=answers)

    book.runs += [run(1, 1, script="print(1)"), run(2, 3, script="print(2)")]
    heard = [turn(1, "person"), turn(3, "person"), turn(4, "ashley", answers=1)]
    said = turn(5, "person")
    got = asyncio.run(carried(10, heard, said, replace(respond_module.LIMITS["chat"], carried_runs=5)))
    assert list(got) == [4]
    assert "print(1)" in got[4] and "print(2)" not in got[4]

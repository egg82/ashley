"""The spend ledger names the conversation: every row `RoutedInference` records for a call carries the id passed to
`generate`, `step`, `transcribe` or `speak` (each route tried, failed or ok), NULL when omitted; the Postgres ledger
stores it in a bigint column with no foreign key; and the memory writer passes the conversation it decides on."""

import asyncio

import psycopg
from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.conversations.model import Conversation
from ashley.inference.inference import Inference
from ashley.inference.model import Prompt, Task, ToolCalls, Usage
from ashley.inference.postgres import PostgresSpendLedger
from ashley.inference.reply import Reply
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.inference.spend import Call
from ashley.memory.eval import write
from ashley.memory.eval.people import CasePeople
from ashley.memory.inference_writer import InferenceFactWriter
from ashley.memory.writer_output import Written
from ashley.people.people import People
from pydantic import BaseModel

from contract_speech_support import FakeSpeechProvider, Hear, Utterance, drain, hear_fail, say_fail, speech_router
from conversations_support import run, scalar
from inference_support import FakeLedger, FakeProvider, fail, ok, prompt, route, router, settle, table
from inference_tools_support import broke, provider, say, tool_prompt
from ashley.inference.model import Message

ID = 5_000_000_001
"""Past 2**31, so a column that is not a bigint cannot hold it."""


def ids(ledger: FakeLedger) -> list[int | None]:
    return [row.conversation_id for row in ledger.rows]


def test_generate_stamps_every_route_tried_with_the_conversation() -> None:
    ledger = FakeLedger()
    inference = router(table([route("alpha"), route("beta")]),
                       [FakeProvider("alpha", [fail("unavailable")]), FakeProvider("beta", [ok()])], ledger)
    settle(inference.generate("chat", prompt("hi"), Reply, conversation_id=ID))
    assert [r.outcome for r in ledger.rows] == ["unavailable", "ok"]
    assert ids(ledger) == [ID, ID]


def test_generate_without_a_conversation_records_none() -> None:
    ledger = FakeLedger()
    inference = router(table([route("alpha"), route("beta")]),
                       [FakeProvider("alpha", [fail("error")]), FakeProvider("beta", [ok()])], ledger)
    settle(inference.generate("chat", prompt("hi"), Reply))
    assert len(ledger.rows) == 2 and ids(ledger) == [None, None]


def test_step_stamps_every_route_tried_with_the_conversation() -> None:
    ledger = FakeLedger()
    inference = router(table([route("a"), route("b")]), [provider("a", broke("unavailable")), provider("b", say())],
                       ledger)
    settle(inference.step("chat", tool_prompt(Message("person", "hi")), Reply, conversation_id=ID))
    assert [r.outcome for r in ledger.rows] == ["unavailable", "ok"]
    assert ids(ledger) == [ID, ID]


def test_step_without_a_conversation_records_none() -> None:
    ledger = FakeLedger()
    settle(router(table([route("a")]), [provider("a", say())], ledger).step(
        "chat", tool_prompt(Message("person", "hi")), Reply))
    assert ids(ledger) == [None]


def test_transcribe_stamps_every_route_tried_with_the_conversation() -> None:
    ledger = FakeLedger()
    a, b = FakeSpeechProvider("a", [hear_fail("error")]), FakeSpeechProvider("b", [Hear("heard")])
    settle(speech_router([route("a"), route("b")], [a, b], ledger).transcribe(
        "transcribe", Utterance().heard, conversation_id=ID))
    assert [r.outcome for r in ledger.rows] == ["error", "ok"]
    assert ids(ledger) == [ID, ID]


def test_transcribe_without_a_conversation_records_none() -> None:
    ledger = FakeLedger()
    settle(speech_router([route("a")], [FakeSpeechProvider("a", [Hear("heard")])], ledger).transcribe(
        "transcribe", Utterance().heard))
    assert ids(ledger) == [None]


def test_speak_stamps_every_route_tried_with_the_conversation() -> None:
    ledger = FakeLedger()
    a, b = FakeSpeechProvider("a", says=[say_fail("error")]), FakeSpeechProvider("b")

    async def scenario() -> None:
        await drain(await speech_router([route("a"), route("b")], [a, b], ledger).speak(
            "speak", "hi", conversation_id=ID))

    settle(scenario())
    assert [r.outcome for r in ledger.rows] == ["error", "ok"]
    assert ids(ledger) == [ID, ID]


def test_speak_without_a_conversation_records_none() -> None:
    ledger = FakeLedger()

    async def scenario() -> None:
        await drain(await speech_router([route("a")], [FakeSpeechProvider("a")], ledger).speak("speak", "hi"))

    settle(scenario())
    assert len(ledger.rows) == 1 and ids(ledger) == [None]


# --- the Postgres ledger ----------------------------------------------------------------------------------------

USAGE = Usage(input_tokens=1, output_tokens=2)


def rows(url: str) -> list[int | None]:
    with psycopg.connect(url, autocommit=True) as conn:
        return [r[0] for r in conn.execute("SELECT conversation_id FROM inference_calls ORDER BY id").fetchall()]


def test_the_ledger_stores_the_conversation_of_a_call_and_null_for_none(db_url: str) -> None:
    async def scenario() -> None:
        db = PoolDatabase(db_url)
        await db.open()
        try:
            spend = PostgresSpendLedger(db)
            await spend.record(Call("chat", "alpha", "m1", "ok", USAGE, None, 1, ID))
            await spend.record(Call("chat", "alpha", "m1", "ok", USAGE, None, 1))
            await spend.record(Call("chat", "alpha", "m1", "ok", USAGE, None, 1, None))
        finally:
            await db.close()

    run(scenario())
    assert rows(db_url) == [ID, None, None]


def test_the_column_is_a_nullable_bigint_with_no_foreign_key(db_url: str) -> None:
    assert scalar(db_url, "SELECT data_type FROM information_schema.columns WHERE table_name = 'inference_calls' "
                          "AND column_name = 'conversation_id'") == "bigint"
    assert scalar(db_url, "SELECT is_nullable FROM information_schema.columns WHERE table_name = 'inference_calls' "
                          "AND column_name = 'conversation_id'") == "YES"
    assert scalar(db_url, "SELECT count(*) FROM pg_constraint WHERE conrelid = 'inference_calls'::regclass "
                          "AND contype = 'f'") == 0


# --- the memory writer --------------------------------------------------------------------------------------------


class Recording(Inference):
    def __init__(self) -> None:
        self.ids: list[int | None] = []

    async def generate[T: BaseModel](self, task: Task, prompt: Prompt, output: type[T], *,
                                     conversation_id: int | None = None) -> T:
        self.ids.append(conversation_id)
        return output.model_validate(Written(ops=()).model_dump())

    async def step[T: BaseModel](self, task: Task, prompt: Prompt, output: type[T], *,
                                 conversation_id: int | None = None) -> T | ToolCalls:
        raise AssertionError("the writer never steps")

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise AssertionError("the writer never transcribes")

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise AssertionError("the writer never speaks")


def test_the_memory_writer_names_the_conversation_it_decides_on() -> None:
    data = write.load()
    case = next(c for c in data["cases"] if c["id"] == "update-changed-preference")
    conversation, known, _ = write.build(data, case)
    named = Conversation(ID, conversation.household_id, conversation.kind, conversation.participants,
                         conversation.started_at, conversation.last_activity_at, conversation.state,
                         conversation.turns)
    recording = Recording()
    services.register(People, CasePeople(data))
    services.register(Inference, recording)
    try:
        asyncio.run(InferenceFactWriter().decide(named, known, write.NOW))
    finally:
        services.unregister(People)
        services.unregister(Inference)
    assert recording.ids == [ID]

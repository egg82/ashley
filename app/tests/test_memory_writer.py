"""`InferenceFactWriter` with a scripted `Inference`: each op kind converts, what code can check is checked (a target
that is not a known fact, a person outside the household, a blank fact), the prompt names every known fact's id and
every turn's speaker, and the eval runner reports passes and the spend its ledger rows show."""

import asyncio
import logging
from collections.abc import Generator
from dataclasses import replace
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from ashley import services
from ashley.conversations.conversations import Conversations
from ashley.channels.devices import Devices
from ashley.channels.voice.clips import Clips
from ashley.db.database import Database
from ashley.db.migrate import migrate
from ashley.db.pool import PoolDatabase
from ashley.evals import __main__ as evals_main
from ashley.evals import memory_write
from ashley.inference import routes
from ashley.inference.inference import Inference
from ashley.inference.postgres import PostgresSpendLedger, Spent
from ashley.inference.router import RoutedInference
from ashley.memory.eval import write
from ashley.memory.eval.people import CasePeople
from ashley.memory.inference_writer import InferenceFactWriter
from ashley.memory.memory import Memory
from ashley.inference.model import Message, Usage
from ashley.inference.spend import Call
from ashley.memory import writer_prompt
from ashley.memory.model import Add, Forget, Invalidate, NewFact, Noop, Op, Update
from ashley.memory.writer_output import Written, WrittenOp
from ashley.people.people import People
from catalogue_support import shipped
from writer_support import ExpectedProvider, ScriptedInference, op

DATA = write.load()
CASE = next(c for c in DATA["cases"] if c["id"] == "update-changed-preference")
KNOWN_ID = write.FIRST_KNOWN_ID
FIRST_TURN = 1
"""The case's only person turn, which a fact naming no shown turn falls back to."""
UNRELATED = Call("chat", "anthropic", "claude-haiku-5-5", "ok", Usage(10, 10), Decimal("1"), 1)
"""A call before the eval's, which its spend must not count."""


@pytest.fixture
def people() -> Generator[None]:
    services.register(People, CasePeople(DATA))
    yield
    services.unregister(People)


def decide(*ops: WrittenOp, case: dict[str, Any] = CASE) -> tuple[tuple[Op, ...], ScriptedInference]:
    inference = ScriptedInference(Written(ops=ops))
    services.register(Inference, inference)
    try:
        conversation, known, _ = write.build(DATA, case)
        return asyncio.run(InferenceFactWriter().decide(conversation, known, write.NOW)), inference
    finally:
        services.unregister(Inference)


def test_each_op_kind_becomes_its_op(people: None) -> None:
    ops, _ = decide(
        op("add", None, 1, 1, "Alana likes tea", visibility="discreet", visibility_stated=True, kind="preference"),
        op("update", KNOWN_ID, 1, 1, "Alana likes the bedroom at 64 degrees", kind="preference"),
        op("invalidate", KNOWN_ID), op("forget", KNOWN_ID), op("noop", KNOWN_ID), op("noop", None))
    assert ops == (
        Add(NewFact(1, 1, "discreet", True, "preference", False, "Alana likes tea", FIRST_TURN)),
        Update(KNOWN_ID, NewFact(1, 1, "shared", False, "preference", False, "Alana likes the bedroom at 64 degrees",
                                    FIRST_TURN)),
        Invalidate(KNOWN_ID), Forget(KNOWN_ID), Noop(KNOWN_ID), Noop(None))


def test_a_household_fact_keeps_no_person_and_an_add_ignores_its_target(people: None) -> None:
    ops, _ = decide(op("add", 12345, None, None, "The spare key is under the mat", kind="home"))
    assert ops == (Add(NewFact(None, None, "shared", False, "home", False, "The spare key is under the mat",
                                  FIRST_TURN)),)


def test_an_added_household_fact_is_its_tellers_only_when_they_said_who_may_know(
        people: None, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, "ashley.memory")
    ops, _ = decide(op("add", None, None, 1, "We run out of coffee by Friday"),
                    op("add", None, None, 1, "The spare key is by the shed", visibility="private",
                       visibility_stated=True),
                    op("add", None, 1, 1, "Alana likes tea"),
                    op("update", KNOWN_ID, None, 1, "The spare key is under the mat"))
    assert [o.fact.owner_id for o in ops if isinstance(o, (Add, Update))] == [None, 1, 1, 1]
    [fields] = [r.__dict__["fields"] for r in caplog.records if r.msg == "memory.write"]
    assert fields["owner_cleared"] == 1


def test_a_target_that_is_not_a_known_fact_is_dropped_and_counted(people: None,
                                                                 caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, "ashley.memory")
    ops, _ = decide(op("update", KNOWN_ID + 1), op("invalidate", 7), op("forget", None), op("noop", 999),
                    op("update", None), op("invalidate", KNOWN_ID))
    assert ops == (Invalidate(KNOWN_ID),)
    fields = [r.__dict__["fields"] for r in caplog.records if r.msg == "memory.write"]
    assert len(fields) == 1 and fields[0]["dropped_unknown_target"] == 5 and fields[0]["written"] == 6
    assert (fields[0]["invalidate"], fields[0]["dropped_unknown_person"]) == (1, 0)


def test_a_person_outside_the_household_is_dropped_whether_about_or_owner(people: None) -> None:
    ops, _ = decide(op("add", None, 3, 1), op("add", None, 1, 3), op("update", KNOWN_ID, 1, 99),
                    op("add", None, 2, 1, "Alana bought Elodie a gift"))
    assert ops == (Add(NewFact(2, 1, "shared", False, "other", False, "Alana bought Elodie a gift", FIRST_TURN)),)


def test_a_blank_fact_is_dropped(people: None) -> None:
    ops, _ = decide(op("add", text="  "), op("update", KNOWN_ID, text=""), op("forget", KNOWN_ID, text=""))
    assert ops == (Forget(KNOWN_ID),)


def test_the_prompt_names_each_known_fact_by_id_and_each_turn_by_its_speaker(people: None) -> None:
    case = {**CASE, "known": [*CASE["known"], {"ref": "k2", "about": "elodie", "owner": "elodie",
                                               "visibility": "discreet", "kind": "plan", "text": "Elodie is away"}],
            "turns": [*CASE["turns"], {"author": "person", "speaker": None, "text": "Who left the door open?"},
                      {"author": "person", "speaker": "elodie", "text": "Not me."}]}
    _, inference = decide(op("noop", None), case=case)
    [(task, prompt)] = inference.asked
    [message] = prompt.messages
    assert isinstance(message, Message)
    text = message.text
    assert task == "memory_write"
    assert f"id {KNOWN_ID}:" in text and f"id {KNOWN_ID + 1}:" in text
    assert "[turn 1] Alana (1): Set the bedroom to 64" in text and "[turn 2] assistant: Bedroom's going" in text
    assert "[turn 3] unknown speaker: Who left the door open?" in text and "[turn 4] Elodie (2): Not me." in text
    assert "- 1: Alana" in text and "- 2: Elodie" in text
    assert prompt.system_for("default").stable == writer_prompt.system() != ""


def test_a_fact_keeps_the_shown_turn_it_names_and_falls_back_to_the_last_person_turn(
        people: None, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, "ashley.memory")
    case = {**CASE, "turns": [*CASE["turns"], {"author": "person", "speaker": "alana", "text": "And I like tea"},
                              {"author": "ashley", "speaker": None, "text": "Noted."}]}
    conversation, _, _ = write.build(DATA, case)
    first, last_person = conversation.turns[0].id, conversation.turns[2].id
    ops, _ = decide(op("add", text="One", source_turn=first), op("add", text="Two", source_turn=4242),
                    op("add", text="Three", source_turn=None), op("noop", None, source_turn=4242), case=case)
    assert [o.fact.source_turn_id for o in ops if isinstance(o, Add)] == [first, last_person, last_person]
    [fields] = [r.__dict__["fields"] for r in caplog.records if r.msg == "memory.write"]
    assert fields["turn_fallback"] == 2


def test_a_conversation_with_no_person_turn_leaves_the_source_turn_unnamed(people: None) -> None:
    case = {**CASE, "turns": [{"author": "ashley", "speaker": None, "text": "Good morning."}]}
    ops, _ = decide(op("add", source_turn=None), case=case)
    assert [o.fact.source_turn_id for o in ops if isinstance(o, Add)] == [None]


def test_a_conversation_from_no_known_household_raises(people: None) -> None:
    conversation, known, _ = write.build(DATA, CASE)
    services.register(Inference, ScriptedInference(Written(ops=())))
    try:
        with pytest.raises(ValueError):
            asyncio.run(InferenceFactWriter().decide(replace(conversation, household_id=2), known, write.NOW))
    finally:
        services.unregister(Inference)


@pytest.fixture
def ledger_database(empty_database: str) -> Generator[str]:
    migrate(empty_database)
    yield empty_database
    for service in (Database, Inference, People, Conversations, Memory, Devices, Clips):
        services.unregister(service)


def test_a_writer_answering_as_each_case_expects_passes_the_harness_and_the_spend_is_read_back(
        ledger_database: str) -> None:
    provider = ExpectedProvider()

    async def scenario() -> memory_write.Outcome:
        db = PoolDatabase(ledger_database, connect_timeout_s=5.0)
        await db.open()
        services.register(Database, db)
        services.register(Inference, RoutedInference(routes.load({"anthropic": provider}), [provider],
                                                     PostgresSpendLedger(db), shipped()))
        try:
            await PostgresSpendLedger(db).record(UNRELATED)
            return await memory_write.run(1, None)
        finally:
            await db.close()

    outcome = asyncio.run(scenario())
    assert [c.case_id for c in outcome.report.cases if c.passes != c.runs] == []
    assert len(outcome.report.cases) == len(DATA["cases"]) and outcome.report.by_source() == {"authored": 1.0, "real": 1.0}
    assert outcome.spent.calls == len(provider.calls) > len(DATA["cases"]) and outcome.spent.unpriced == 0
    assert outcome.spent.cost_usd > 0
    with psycopg.connect(ledger_database, autocommit=True) as conn:
        total = conn.execute(b"SELECT sum(cost_usd) FROM inference_calls WHERE task <> 'chat'").fetchone()
    assert total is not None and Decimal(total[0]) == outcome.spent.cost_usd
    rendered = memory_write.render(outcome)
    assert "authored: 100%" in rendered and "real: 100%" in rendered and "answered: memory_write" in rendered and "MIXED" not in rendered
    marked = {line.split()[-3] for line in rendered.splitlines() if line.endswith("(known failing)")}
    assert marked == {c["id"] for c in DATA["cases"] if c.get("known_failing")}
    assert sum(b.spent.calls for b in outcome.by) == outcome.spent.calls


def test_a_known_failing_case_is_marked_and_counted_in_its_rate() -> None:
    cases = (write.WriteCaseResult("a", "real", 2, 0, ("x", "x"), known_failing=True),
             write.WriteCaseResult("b", "real", 2, 2, ()))
    rendered = memory_write.render(memory_write.Outcome(write.WriteReport(cases), Spent(0, Decimal(0), 0), []))
    assert "0/2    0%  real      a  (known failing)\n" in rendered and "2/2  100%  real      b\n" in rendered
    assert "real: 50%" in rendered


def test_the_runner_wires_from_the_environment_and_fails_when_no_model_answers(
        ledger_database: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "LOCAL_LLM_URL", "HA_URL", "HA_TOKEN",
                "ETCD_URL", "WYOMING_STT_URL", "ELEVENLABS_API_KEY", "VOICE_CLIP_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert evals_main.main(["memory-write"]) == 2
    monkeypatch.setenv("DATABASE_URL", ledger_database)
    assert evals_main.main(["memory-write", "--runs", "0"]) == 2
    assert evals_main.main(["memory-write", "--case", "no-such-case"]) == 1
    assert evals_main.main(["memory-write", "--case", CASE["id"]]) == 1
    err = capsys.readouterr().err
    assert "no write case 'no-such-case'" in err and "inference failed: InferenceUnavailable" in err


def test_a_nul_in_a_written_fact_is_removed(people: None) -> None:
    ops, _ = decide(op("add", text="a\u0000b"))
    assert isinstance(ops[0], Add) and ops[0].fact.text == "ab"

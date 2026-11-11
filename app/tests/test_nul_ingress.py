"""Outside text that holds a NUL (U+0000), which no Postgres text column or jsonb can hold, must not stop the turn it
arrives in: voice transcripts and mail are cleaned where they enter, and the rest of the words still arrive."""

import asyncio
import base64

import pytest
from aioesphomeapi.model import VoiceAssistantEventType as Event
from ashley import logs
from ashley.channels.checkpoint import Checkpoint, dumps, loads
from ashley.channels.model import on_bench
from ashley.channels.tool_loop import Progress
from ashley.conversations.model import NewTurn
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from ashley.mail import body, imap_message
from ashley.mail.gmail_shapes import Body, Part
from ashley.inference.model import Message, SystemPrompt, ToolResult
from contract.conversations_support import POLICY, db_url as db_url, events, household
from contract.conversations_support import migrated_template as migrated_template, scalar
from nul_ingress_support import heard
from voice_support import satellite_row

NUL = "\x00"


def test_a_transcript_with_a_nul_is_stored_with_the_nul_removed(db_url: str) -> None:
    satellite = satellite_row(db_url, household(db_url))
    heard(db_url, satellite, f"turn the li{NUL}ghts off")
    assert scalar(db_url, "SELECT text FROM turns WHERE author = 'person'") == "turn the lights off"


def test_a_tool_result_with_a_nul_survives_in_the_checkpoint_of_the_turn_that_read_it(db_url: str) -> None:
    text = f"hello{NUL}world"

    async def scenario() -> str:
        db = PoolDatabase(db_url)
        await db.open()
        try:
            home = household(db_url)
            conversations = PostgresConversations(db, POLICY)
            made = await conversations.start(home, "command", [])
            said = await conversations.add_turn(made.id, NewTurn("person", "read my mail", None))
            progress = Progress((Message("person", "read my mail"),), 1, 1, None,
                                {"c1": ToolResult("c1", text)}, ())
            checkpoint = Checkpoint(on_bench(1, 2, 3, "hi"), made.id, said.id, None, {"default": SystemPrompt("s", "m")},
                                    progress)
            await PostgresInFlight(db, POLICY, 60.0).begin(made.id, said.id, dumps(checkpoint))
            return str(scalar(db_url, "SELECT checkpoint FROM turn_work"))
        finally:
            await db.close()

    stored = asyncio.run(scenario())
    assert loads(stored).progress.done["c1"].content == text


def test_a_transcript_with_a_nul_logs_how_many_went_and_nothing_else(db_url: str,
                                                                    capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    heard(db_url, satellite_row(db_url, household(db_url)), f"a{NUL}b{NUL}c")
    [line] = events(capsys.readouterr().out, "text.nul_stripped")
    assert (line["channel"], line["count"]) == ("voice", "2")
    assert "abc" not in str(line)


def test_a_transcript_of_only_nuls_is_an_empty_one(db_url: str) -> None:
    link = heard(db_url, satellite_row(db_url, household(db_url)), NUL * 3)
    assert scalar(db_url, "SELECT count(*) FROM turns") == 0
    assert Event.VOICE_ASSISTANT_STT_END not in link.kinds()


def test_an_imap_body_has_its_nuls_removed(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    raw = (b"From: a@example.test\r\nSubject: s\r\nContent-Type: text/plain; charset=utf-8\r\n"
           b"Content-Transfer-Encoding: base64\r\n\r\n" + base64.b64encode(b"hello\x00world\x00") + b"\r\n")
    text, _ = imap_message.text_and_attachments(imap_message.parse(raw))
    assert text == "helloworld"
    [line] = events(capsys.readouterr().out, "text.nul_stripped")
    assert (line["channel"], line["count"]) == ("mail", "2")


def test_a_gmail_body_has_its_nuls_removed() -> None:
    data = base64.urlsafe_b64encode(b"<p>hel\x00lo</p>").decode()
    payload = Part(mimeType="multipart/alternative", parts=[Part(mimeType="text/html", body=Body(size=1, data=data))])
    assert body.text_and_attachments(payload)[0] == "hello"

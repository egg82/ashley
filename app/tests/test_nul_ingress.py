"""Outside text that holds a NUL (U+0000), which no Postgres text column or jsonb can hold, must not stop the turn it
arrives in: voice transcripts and mail are cleaned where they enter, and the rest of the words still arrive."""

import asyncio

import pytest
from ashley.channels.checkpoint import Checkpoint, dumps, loads
from ashley.channels.model import on_bench
from ashley.channels.tool_loop import Progress
from ashley.conversations.model import NewTurn
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from ashley.inference.model import Message, SystemPrompt, ToolResult
from contract.conversations_support import POLICY, db_url as db_url, household
from contract.conversations_support import migrated_template as migrated_template, scalar
from nul_ingress_support import heard
from voice_support import satellite_row

NUL = "\x00"


@pytest.mark.xfail(strict=True, reason="a transcript with a NUL is forwarded as it is, and its turn is refused")
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

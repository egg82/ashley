"""Directed, not blind: `get` reads the conversation, its participants and its turns as one snapshot, so a turn
committed while it reads cannot leave `last_activity_at` older than the newest turn it returns."""

import asyncio

from ashley.conversations.model import NewTurn
from conversations_support import blocked_backend, holding, household, person, run, service


def test_a_turn_committed_mid_read_is_seen_whole_or_not_at_all(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conversations:
            started = await conversations.start(home, "chat", [alana])
            await conversations.add_turn(started.id, NewTurn("person", "first", alana))
            # `get` reads the conversation row, then stalls on the participants until this commits a second turn.
            async with holding(db_url, "LOCK TABLE conversation_participants IN ACCESS EXCLUSIVE MODE", ()) as lock:
                reading = asyncio.create_task(conversations.get(started.id))
                await blocked_backend(db_url)
                await lock.execute("INSERT INTO turns (conversation_id, household_id, author, text, at) "
                                   "VALUES (%s, %s, 'ashley', 'second', clock_timestamp())", (started.id, home))
                await lock.execute("UPDATE conversations SET last_activity_at = (SELECT max(at) FROM turns "
                                   "WHERE conversation_id = %s) WHERE id = %s", (started.id, started.id))
            seen = await reading
        assert seen is not None
        assert seen.last_activity_at == seen.turns[-1].at, [t.text for t in seen.turns]

    run(scenario())

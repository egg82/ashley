"""Outside text carrying a NUL, carried through the real code to a real database: a voice satellite's transcript, and a
mail body read by a tool and kept in a turn's checkpoint."""

import asyncio

from ashley import services
from ashley.channels import person_turn
from ashley.channels.model import Inbound, Outbound, Satellite
from ashley.channels.voice.clips import Clips
from ashley.channels.voice.postgres_clips import PostgresClips
from ashley.channels.voice.run import Run
from ashley.conversations.conversations import Conversations
from ashley.conversations.postgres import PostgresConversations
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference
from contract.conversations_support import POLICY
from voice_support import FRAME, FakeLink, FakeSpeech, FakeTurnLoop, pipeline


class StoringLoop(FakeTurnLoop):
    """The turn loop's first step, the person's turn stored, with nothing after it."""

    async def __call__(self, inbound: Inbound) -> Outbound:
        conversation, _ = await person_turn.stored(inbound, None)
        return Outbound(conversation.id, "spoken", "Noted.", follows=False)


def heard(url: str, satellite: Satellite, transcript: str) -> FakeLink:
    """One wake whose transcript is `transcript`, its person turn stored through the real conversations."""
    link = FakeLink()
    services.register(Inference, FakeSpeech(transcript=transcript))

    async def scenario() -> None:
        database = PoolDatabase(url)
        await database.open()
        services.register(Clips, PostgresClips(database, 120))
        services.register(Conversations, PostgresConversations(database, POLICY))
        try:
            run = Run(satellite, link, pipeline(StoringLoop()))
            for _ in range(20):
                run.audio(FRAME)
            run.end_audio()
            await asyncio.wait_for(run.go(), 5)
        finally:
            for interface in (Inference, Clips, Conversations):
                services.unregister(interface)
            await database.close()

    asyncio.run(scenario())
    return link


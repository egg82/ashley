"""The turn loop and remembered conversations: an `Inbound` with `remembers=False` starts a conversation stored as not
remembered; one that remembers (the default) starts a remembered one. And every reply step names the conversation."""

from dataclasses import replace

import pytest
from ashley import services
from ashley.channels.respond import respond
from ashley.conversations.conversations import Conversations
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference
from ashley.inference.model import Prompt, Task, ToolCalls
from ashley.inference.reply import Reply
from pydantic import BaseModel

from conversations_support import make, run, scalar
from inference_support import settle
from turns_support import HOUSE, FakeInference, World, asks, inbound, world as world


class RecordingInference(FakeInference):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[int | None] = []

    async def step[T: BaseModel](self, task: Task, prompt: Prompt, output: type[T], *,
                                 conversation_id: int | None = None) -> T | ToolCalls:
        self.ids.append(conversation_id)
        return await super().step(task, prompt, output, conversation_id=conversation_id)


@pytest.mark.parametrize("remembers", [True, False])
def test_a_message_starts_a_conversation_stored_as_its_device_remembers(db_url: str, world: World,
                                                                       remembers: bool) -> None:
    scalar(db_url, "INSERT INTO households (id, name) OVERRIDING SYSTEM VALUE VALUES (%s, 'home') RETURNING id",
           (HOUSE,))

    async def scenario() -> None:
        db = PoolDatabase(db_url)
        await db.open()
        services.register(Conversations, make(db))
        try:
            out = await respond(replace(inbound(), remembers=remembers))
            assert scalar(db_url, "SELECT remembered FROM conversations WHERE id = %s", (out.conversation_id,)) \
                is remembers
        finally:
            await db.close()

    run(scenario())


def test_the_default_inbound_starts_a_remembered_conversation(db_url: str, world: World) -> None:
    scalar(db_url, "INSERT INTO households (id, name) OVERRIDING SYSTEM VALUE VALUES (%s, 'home') RETURNING id",
           (HOUSE,))

    async def scenario() -> None:
        db = PoolDatabase(db_url)
        await db.open()
        services.register(Conversations, make(db))
        try:
            out = await respond(inbound())
            assert scalar(db_url, "SELECT remembered FROM conversations WHERE id = %s", (out.conversation_id,)) is True
        finally:
            await db.close()

    run(scenario())


def test_every_reply_step_names_the_conversation_it_serves(world: World) -> None:
    recording = RecordingInference()
    recording.script = [asks("lights"), Reply(spoken="done", text="done")]
    services.register(Inference, recording)
    out = settle(respond(inbound()))
    assert len(recording.ids) >= 2, "a tool round and the final reply are two steps"
    assert recording.ids == [out.conversation_id] * len(recording.ids)

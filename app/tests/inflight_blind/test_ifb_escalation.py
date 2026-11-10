"""An escalated turn survives its pod: the trigger is saved in the work's checkpoint (`Saved.escalate`), and the runner
that resumes it asks the stronger route (task `escalated`), once, and stores one reply."""

from dataclasses import dataclass, field
from typing import Any

from ashley import logs, services
from ashley.channels import resume
from ashley.channels.checkpoint import Checkpoint, dumps, loads
from ashley.channels.inflight import Saved
from ashley.channels.model import Inbound
from ashley.channels.tool_loop import Progress
from ashley.conversations.inflight import Claim
from ashley.inference.inference import Inference
from ashley.inference.model import Message, Prompt, Task
from contract.conversations_support import events, run
from ifb_resume_support import DONE, SYSTEM, Model, World, world


@dataclass
class Tasked(Model):
    tasks: list[Task] = field(default_factory=list[Task])

    async def step(self, task: Task, prompt: Prompt, output: type[Any], *, conversation_id: int | None = None) -> Any:
        self.tasks.append(task)
        return await super().step(task, prompt, output, conversation_id=conversation_id)


async def begun(w: World, progress: Progress) -> tuple[Saved, Claim]:
    conv_id, said_id = await w.r.said("web:1", "remind me about the deposit")
    inbound = Inbound(w.r.home, "web:1", "remind me about the deposit", "chat", "text", "owner", w.r.who, False, None,
                      "web", later=True, later_by="turn", opens_benches=True, on_page=True)
    saved = Checkpoint(inbound, conv_id, said_id, w.r.who, {"default": SYSTEM}, progress)
    claim = await w.r.inflight.begin(conv_id, said_id, dumps(saved))
    return Saved(claim, saved), claim


def tasked(w: World) -> Tasked:
    model = Tasked(w.model.script, w.model.prompts)
    services.unregister(Inference)
    services.register(Inference, model)
    return model


def test_the_saved_trigger_is_in_the_checkpoint_the_next_runner_reads(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            work, claim = await begun(w, Progress((Message("person", "x"),), 0, 0))
            await work.escalate("b")
            assert work.escalated == "b"
            await w.r.expire(claim)
            (orphan,) = await w.r.inflight.orphaned(5)
            assert loads(orphan.checkpoint).escalated == "b"

    run(go())


def test_a_resumed_escalated_turn_asks_the_stronger_route_and_stores_one_reply(db_url: str, capsys: Any) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            model = tasked(w)
            work, claim = await begun(w, Progress((Message("person", "remind me about the deposit"),), 3, 3))
            await work.escalate("a")
            await w.r.expire(claim)
            model.script = [DONE]
            logs.setup()
            capsys.readouterr()
            assert await resume.sweep() == 1
            assert model.tasks == ["escalated"] and await w.r.hers() == [DONE.text]
            assert events(capsys.readouterr().out, "respond.escalated") == []
            assert await resume.sweep() == 0 and await w.r.hers() == [DONE.text]

    run(go())


def test_a_resumed_turn_that_had_not_escalated_asks_the_fast_route(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            model = tasked(w)
            _, claim = await begun(w, Progress((Message("person", "x"),), 0, 0))
            await w.r.expire(claim)
            model.script = [DONE]
            assert await resume.sweep() == 1 and model.tasks == ["chat"]

    run(go())

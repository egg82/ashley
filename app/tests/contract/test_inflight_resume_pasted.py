"""A turn started `pasted` and resumed on another pod keeps its origin and keeps the block out of the judge's words
(`decisions.md`, "Work in flight survives its pod"): the saved checkpoint holds the origin and her prompt with the block, the
Inbound in it carries no copy, the block stays on the stored person turn, and the words read for the resumed turn are
the typed text alone.

Postgres is real (Conversations, `InFlight`); the model and the tools are fakes, as in `test_inflight_resume.py`."""

from dataclasses import replace

from ashley import services
from ashley.channels import judge_words, pasted
from ashley.channels.checkpoint import loads
from ashley.channels.model import Inbound
from ashley.conversations.conversations import Conversations
from ashley.conversations.model import Attachment
from contract.conversations_support import run, scalar
from contract.conversations_support import db_url as db_url
from contract.conversations_support import migrated_template as migrated_template
from contract.test_inflight_resume import DONE, HANG, World, database
from contract.test_inflight_resume import system as system
from contract.test_inflight_resume import world as world
from contract.test_inflight_resume_channels import killed, resumed

TYPED = "what should I do about this?"
BLOCK = Attachment("Forwarded", "zqPASTED " * (pasted.threshold() // 9 + 2))


def pasted_turn(world: World) -> Inbound:
    return replace(world.inbound(), text=TYPED, attachment=BLOCK, taint=pasted.taint_of(BLOCK))


def test_a_resumed_pasted_turn_keeps_its_origin_and_never_reads_the_block_as_words(world: World) -> None:
    world.first.inference.script = [HANG]
    world.second.inference.script = [DONE]
    seen: list[tuple[str | None, Attachment | None, tuple[str, ...]]] = []

    async def go() -> None:
        async with database(world):
            await killed(world, pasted_turn(world), world.first.inference.asked)
            saved = loads(str(scalar(world.url, "SELECT checkpoint FROM turn_work")))
            read = judge_words.reader(saved.inbound, saved.conversation_id, 12, 2000)
            seen.append((saved.tainted, saved.inbound.attachment, tuple(await read())))
            assert saved.inbound.taint == "pasted"
            assert "zqPASTED" in str(scalar(world.url, "SELECT checkpoint FROM turn_work")), "her prompt keeps the block"
            kept = await services.get(Conversations).get(saved.conversation_id)
            assert kept is not None and [t.attachment for t in kept.turns if t.author == "person"] == [BLOCK]
            await resumed(world)

    run(go())
    assert seen == [("pasted", None, (TYPED,))]

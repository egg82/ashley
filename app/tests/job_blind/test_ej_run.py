"""One run: the messages, the system prompt, the task, the limits, no hold, and the tools it uses."""

from dataclasses import replace

from ashley.inference.model import ToolResults
from job_blind_support import (ASK, ASKER_NAME, CONF, GOOD, INSTRUCTIONS, LIST_TOOL, RESULT_TEXT, TASK, TOOL_ARG,
                               TOOL_OUT, World, row, scenario, use_list)
from ashley.inference.reply import Reply


def test_a_run_is_the_errand_task(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.owe()
        w.model.play(use_list(), GOOD)
        await w.tick()
        assert len(w.model.tasks) == 2 and set(w.model.tasks) == {TASK}

    scenario(db_url, body)


def test_the_messages_are_the_conversation_through_the_ask_and_no_further(db_url: str) -> None:
    async def body(w: World) -> None:
        for i in range(1, 6):
            w.say(f"zq-before-{i}", "person" if i % 2 else "ashley")
        await w.owe()
        w.say("zq-after-1", "ashley")
        w.say("zq-after-2")
        await w.tick()
        text = " | ".join(w.model.message_texts())
        assert "zq-after-1" not in text and "zq-after-2" not in text
        assert ASK in w.model.message_texts()[-1]

    scenario(db_url, body)


def test_only_the_last_context_turns_are_read(db_url: str) -> None:
    async def body(w: World) -> None:
        for i in range(1, 6):
            w.say(f"zq-before-{i}", "person" if i % 2 else "ashley")
        await w.owe()
        await w.tick()
        text = " | ".join(w.model.message_texts())
        kept = [f"zq-before-{i}" for i in range(1, 6) if f"zq-before-{i}" in text]
        assert kept == ["zq-before-3", "zq-before-4", "zq-before-5"][-(CONF.context_turns - 1):]
        assert "zq-before-1" not in text and "zq-before-2" not in text

    scenario(db_url, body)


def test_context_turns_comes_from_the_config(db_url: str) -> None:
    async def body(w: World) -> None:
        for i in range(1, 4):
            w.say(f"zq-before-{i}", "person" if i % 2 else "ashley")
        await w.owe()
        await w.tick()
        text = " | ".join(w.model.message_texts())
        assert "zq-before-3" in text and "zq-before-2" not in text and "zq-before-1" not in text

    scenario(db_url, body, replace(CONF, context_turns=2))


def test_the_system_prompt_carries_the_catalogues_guidance_and_names_the_asker(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.owe()
        await w.tick()
        system = w.model.system_text()
        assert INSTRUCTIONS in system and "# Tools" in system
        assert ASKER_NAME in system

    scenario(db_url, body)


def test_the_run_offers_the_catalogues_tools(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.owe()
        await w.tick()
        assert [t.name for t in w.model.prompts[0].tools] == [LIST_TOOL.name]

    scenario(db_url, body)


def test_a_tool_the_model_asks_for_is_run_and_the_errand_still_finishes(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        w.model.play(use_list(), GOOD)
        await w.tick()
        assert [c.arguments.get("item") for c in w.tools.ran] == [TOOL_ARG]
        last = w.model.prompts[-1].messages[-1]
        assert isinstance(last, ToolResults) and TOOL_OUT in str(last)
        r = row(w.url, eid)
        assert r["state"] == "done" and r["result"] == RESULT_TEXT

    scenario(db_url, body)


def test_the_tool_rounds_are_capped_by_the_configs_max_tool_rounds(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        w.model.play(*[use_list(f"c{i}") for i in range(10)])
        await w.tick()
        assert len(w.tools.ran) == CONF.max_tool_rounds
        assert len(w.model.prompts) == CONF.max_tool_rounds + 1
        assert w.model.prompts[-1].tool_choice == "none"
        assert row(w.url, eid)["attempts"] == 1

    scenario(db_url, body)


def test_a_reply_that_is_not_the_answer_is_asked_again_not_held(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        w.model.play(Reply(answers=False, spoken="Let me check.", text="Let me check."), GOOD)
        await w.tick()
        assert [p.tool_choice for p in w.model.prompts] == ["auto", "auto"]
        r = row(w.url, eid)
        assert r["state"] == "done" and r["result"] == RESULT_TEXT

    scenario(db_url, body)

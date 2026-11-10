"""A tool result longer than the cap of the conversation is cut visibly (`tools.cut`), and no tool offered to her
makes a result longer than the smallest cap, so a page of a file is never cut by the loop."""

import json
import logging

import pytest
from ashley.channels import turn_tools
from ashley.channels.limits import load, smallest_result_chars
from ashley.channels.tool_loop import answer
from ashley.inference.model import Message, SystemPrompt, ToolCall, ToolCalls, ToolResult, ToolResults
from ashley.inference.reply import Reply
from ashley.tools import cut, file_page
from inference_support import settle
from turns_support import SPEC, World, world as world

from ashley.channels.limits import Limits

LIMITS = Limits(max_tool_rounds=4, max_tool_result_chars=300, recent_turns=1, relevant_turns=0)


def test_a_result_that_fits_is_left_alone() -> None:
    assert cut.visible("x" * 300, 300) is None


@pytest.mark.parametrize("limit", [1, 50, 120, 300, 5000])
def test_a_cut_result_never_passes_the_limit_and_says_how_much_of_how_much(limit: int) -> None:
    got = cut.visible("abc" * 3000, limit)
    assert got is not None and len(got.text) <= limit and got.total == 9000
    if got.shown:
        assert got.text.startswith(f"[cut: only the first {got.shown} of 9000 characters")
        assert got.text.endswith(("abc" * 3000)[:got.shown])


def test_the_loop_gives_the_model_the_cut_and_logs_it(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="ashley.tools")
    body = json.dumps({"text": "x" * 1000, "truncated": False})
    world.tools.results["lights"] = ToolResult("x", body)
    world.inference.script = [ToolCalls((ToolCall("a", "lights", {}),)), Reply(spoken="ok", text="ok")]
    settle(answer("chat", {"default": SystemPrompt("x")}, (Message("person", "hi"),), (SPEC,), LIMITS, conversation_id=7))
    seen = [e for e in world.inference.asked[-1].prompt.messages if isinstance(e, ToolResults)][0].results[0].content
    assert seen.startswith("[cut: only the first") and f"of {len(body)} characters" in seen and len(seen) <= 300
    found = [getattr(r, "fields") for r in caplog.records if r.getMessage() == "tools.cut"]
    assert len(found) == 1 and found[0]["tool"] == "lights" and found[0]["chars"] == len(body)
    assert found[0]["limit"] == 300 and found[0]["conversation"] == 7 and 0 < found[0]["shown"] < 300


def _read_all(text: str, budget: int) -> list[dict[str, object]]:
    pages: list[dict[str, object]] = []
    start = 0
    while True:
        page = file_page.page("f.md", text, start, False, budget)
        pages.append(page)
        if page["next_start"] is None:
            return pages
        assert isinstance(page["next_start"], int) and page["next_start"] > start
        start = page["next_start"]


def test_a_file_longer_than_a_page_is_read_in_pages_that_find_a_word_past_the_first() -> None:
    text = ("line with \"quotes\" and a newline\n" * 400) + "the word herdr appears here\n" + ("tail\n" * 50)
    budget = smallest_result_chars(load())
    pages = _read_all(text, budget)
    assert len(pages) > 1 and "herdr" not in str(pages[0]["text"])
    assert "".join(str(p["text"]) for p in pages) == text
    assert any("herdr" in str(p["text"]) for p in pages)
    assert all(len(json.dumps(p, ensure_ascii=False)) <= budget for p in pages)
    assert all(p["total_chars"] == len(text) for p in pages) and pages[-1]["next_start"] is None


def test_a_page_of_escape_heavy_text_still_fits_the_budget() -> None:
    text = '"\n\\' * 4000
    assert all(len(json.dumps(p, ensure_ascii=False)) <= 8000 for p in _read_all(text, 8000))


def test_the_code_host_is_built_for_the_smallest_cap_of_any_kind() -> None:
    assert turn_tools.READABLE_CHARS == min(l.max_tool_result_chars for l in load().values())

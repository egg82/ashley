"""`Inference.embed` and `Inference.warm` beyond `tests/test_embed.py`: no routes wired, resting after `unavailable`
and not after `error`, the `inference.call` line without the texts, and `warm` refusing other tasks before it does
anything. Written blind from the docstrings."""

from datetime import date
from typing import Any, get_args

import pytest
from ashley import logs
from ashley.inference.inference import InferenceUnavailable
from ashley.inference.model import Route, Task
from ashley.inference.prices import Prices
from ashley.inference.provider import ProviderFailed
from ashley.inference.router import RoutedInference
from ashley.inference.routes import Routes
from conversations_support import events
from embed_support import ScriptedEmbedder, embed_router
from speech_support import MemoryLedger, run

MARK = "zqPLANTED9921"


def test_with_no_embed_route_wired_embed_is_unavailable_and_warm_returns_quietly() -> None:
    ledger = MemoryLedger()
    bare = RoutedInference(Routes({t: (Route("none", "m", 1.0),) for t in get_args(Task)}, 300.0),
                           [ScriptedEmbedder("a")], ledger, Prices({}), today=lambda: date(2026, 10, 26))
    with pytest.raises(InferenceUnavailable):
        run(bare.embed(["q"], "query"))
    assert run(bare.warm("embed")) is None
    assert ledger.calls == []


def test_a_provider_that_failed_unavailable_rests_and_one_that_errored_is_tried_again() -> None:
    down = ScriptedEmbedder("a", error=ProviderFailed("unavailable", "x"))
    inference, _ = embed_router(down, ScriptedEmbedder("b"))
    run(inference.embed(["q"], "query"))
    run(inference.embed(["q"], "query"))
    assert len(down.seen) == 1

    broken = ScriptedEmbedder("a", error=ProviderFailed("error", "x"))
    inference, _ = embed_router(broken, ScriptedEmbedder("b"))
    run(inference.embed(["q"], "query"))
    run(inference.embed(["q"], "query"))
    assert len(broken.seen) == 2


def test_the_call_line_names_role_and_characters_and_never_the_texts(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    inference, _ = embed_router(ScriptedEmbedder("a"))
    capsys.readouterr()
    run(inference.embed([MARK, MARK + "2"], "passage"))
    out = capsys.readouterr().out
    [line] = events(out, "inference.call")
    assert "passage" in line.values() and str(2 * len(MARK) + 1) in line.values()
    assert MARK not in out


def test_a_failed_embed_call_line_carries_the_reason(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    inference, _ = embed_router(ScriptedEmbedder("a", error=ProviderFailed("error", "BoomType")),
                                ScriptedEmbedder("b"))
    capsys.readouterr()
    run(inference.embed(["x"], "passage"))
    failed, answered = events(capsys.readouterr().out, "inference.call")
    assert failed["reason"] == "BoomType"
    assert "reason" not in answered


@pytest.mark.parametrize("task", ["command", "chat", "memory_write", "transcribe", "nonsense"])
def test_warm_refuses_any_other_task_before_touching_a_provider(task: Any) -> None:
    provider = ScriptedEmbedder("a")
    inference, ledger = embed_router(provider)
    with pytest.raises(ValueError):
        run(inference.warm(task))
    assert provider.seen == [] and ledger.calls == []

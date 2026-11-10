"""`Inference.embed` through the router and the shipped routes, and `FastEmbedder` with its model stubbed out."""

import math
from datetime import date
from collections.abc import Iterable
from typing import Any

import pytest
from ashley.inference import fastembed_embedder, prices, routes
from ashley.inference.fastembed_embedder import FastEmbedder
from ashley.inference.inference import InferenceUnavailable, NullInference
from ashley.inference.model import Usage
from ashley.inference.provider import ProviderFailed
from embed_support import ScriptedEmbedder, embed_router
from speech_support import run


def test_the_first_route_that_answers_is_the_embedding_and_costs_one_row() -> None:
    first, second = ScriptedEmbedder("a"), ScriptedEmbedder("b")
    inference, ledger = embed_router(first, second)
    embedded = run(inference.embed(["one", "two"], "passage"))
    assert embedded.model == "a-model" and len(embedded.vectors) == 2
    assert second.seen == [] and first.seen == [("a-model", ("one", "two"), "passage")]
    [call] = ledger.calls
    assert (call.task, call.provider, call.outcome) == ("embed", "a", "ok")
    assert call.usage == Usage(0, 0, characters=6)


def test_a_failing_route_falls_through_and_none_answering_is_unavailable() -> None:
    down = ScriptedEmbedder("a", error=ProviderFailed("unavailable", "x"))
    inference, ledger = embed_router(down, ScriptedEmbedder("b"))
    assert run(inference.embed(["q"], "query")).model == "b-model"
    assert [c.outcome for c in ledger.calls] == ["unavailable", "ok"]
    with pytest.raises(InferenceUnavailable):
        run(embed_router(ScriptedEmbedder("a", error=ProviderFailed("error", "x")))[0].embed(["q"], "query"))


@pytest.mark.parametrize("texts", [[], ["fine", "  "]])
def test_no_text_or_a_blank_one_is_refused_before_any_call(texts: list[str]) -> None:
    provider = ScriptedEmbedder("a")
    inference, ledger = embed_router(provider)
    with pytest.raises(ValueError):
        run(inference.embed(texts, "query"))
    assert provider.seen == [] and ledger.calls == []


def test_the_shipped_embed_route_is_priced_at_zero_and_unwired_without_a_provider() -> None:
    loaded = routes.load({"fastembed": FastEmbedder("fastembed", "/nowhere")})
    [route] = loaded.for_task("embed")
    assert route.provider == "fastembed"
    cost = prices.load().cost_usd(route.provider, route.model, Usage(0, 0, characters=40), date(2026, 10, 26))
    assert cost is not None and cost == 0
    with pytest.raises(InferenceUnavailable):
        run(NullInference().embed(["q"], "query"))


class StubModel:
    loaded: list[tuple[str, dict[str, Any]]] = []

    def __init__(self, name: str, **kwargs: Any) -> None:
        StubModel.loaded.append((name, kwargs))

    def query_embed(self, texts: Iterable[str]) -> list[list[float]]:
        return [[3.0, 4.0] for _ in texts]

    def passage_embed(self, texts: Iterable[str]) -> list[list[float]]:
        return [[0.0, 2.0] for _ in texts]


def test_fastembed_loads_each_model_once_offline_and_returns_unit_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    StubModel.loaded = []
    monkeypatch.setattr(fastembed_embedder, "TextEmbedding", StubModel)
    embedder = FastEmbedder("fastembed", "/models")
    query = run(embedder.embed("m", {}, ["a", "b"], "query", 5.0))
    passage = run(embedder.embed("m", {}, ["a"], "passage", 5.0))
    assert query == [[0.6, 0.8]] * 2 and passage == [[0.0, 1.0]]
    assert all(math.isclose(math.hypot(*v), 1.0) for v in query + passage)
    assert StubModel.loaded == [("m", {"cache_dir": "/models", "threads": 1, "local_files_only": True})]


def test_a_model_that_cannot_be_loaded_rests_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str, **kwargs: Any) -> None:
        raise ValueError("not in the cache")

    monkeypatch.setattr(fastembed_embedder, "TextEmbedding", missing)
    with pytest.raises(ProviderFailed) as failed:
        run(FastEmbedder("fastembed", "/models").embed("m", {}, ["a"], "query", 5.0))
    assert failed.value.failure == "unavailable"


def test_warming_loads_the_model_unbilled_and_only_speak_and_embed_may_be_warmed(
        monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    StubModel.loaded = []
    monkeypatch.setattr(fastembed_embedder, "TextEmbedding", StubModel)
    embedder = FastEmbedder("fastembed", "/models")
    inference, ledger = embed_router(embedder)
    with caplog.at_level("INFO", logger="ashley.inference"):
        run(inference.warm("embed"))
    assert [name for name, _ in StubModel.loaded] == ["fastembed-model"] and ledger.calls == []
    assert "inference.warm" in caplog.text and "'outcome': 'ok'" in _fields(caplog)
    run(inference.embed(["q"], "query"))
    assert len(StubModel.loaded) == 1
    with pytest.raises(ValueError):
        run(inference.warm("transcribe"))


def test_a_model_that_cannot_warm_is_logged_and_never_raises(monkeypatch: pytest.MonkeyPatch,
                                                              caplog: pytest.LogCaptureFixture) -> None:
    def missing(name: str, **kwargs: Any) -> None:
        raise ValueError("not in the cache")

    monkeypatch.setattr(fastembed_embedder, "TextEmbedding", missing)
    inference, _ = embed_router(FastEmbedder("fastembed", "/models"))
    with caplog.at_level("INFO", logger="ashley.inference"):
        run(inference.warm("embed"))
    assert "'outcome': 'unavailable'" in _fields(caplog)


def _fields(caplog: pytest.LogCaptureFixture) -> str:
    return " ".join(str(getattr(r, "fields", "")) for r in caplog.records)

"""Image calls through `RoutedInference`: routes in order with fallback, a refusal final, every failure kind named when
none drew, the household's limit checked before any provider, and one ledger row and log line per call made."""

import logging

import pytest
from ashley.inference.inference import ImageCapped, ImageUnavailable, InferenceRefused
from ashley.inference.provider import ProviderFailed, ProviderRefused
from image_support import JPEG, ScriptedMaker, router
from speech_support import failing, run

ASK = dict(household_id=1, conversation_id=7)


def test_the_first_route_that_draws_answers_and_the_call_is_recorded() -> None:
    first, second = ScriptedMaker("a"), ScriptedMaker("b")
    inference, ledger = router(first, second)
    drawn = run(inference.make_image("a lamp", "square", **ASK))
    assert (drawn.data, drawn.media_type, drawn.provider, drawn.model) == (JPEG, "image/jpeg", "a", "a-model")
    assert second.asked == []
    [call] = ledger.calls
    assert (call.task, call.provider, call.outcome, call.conversation_id) == ("image", "a", "ok", 7)


def test_a_failed_route_falls_back_to_the_next_and_is_recorded() -> None:
    inference, ledger = router(ScriptedMaker("a", error=failing("invalid_output")), ScriptedMaker("b"))
    assert run(inference.make_image("a lamp", "tall", **ASK)).provider == "b"
    assert [(c.provider, c.outcome) for c in ledger.calls] == [("a", "invalid_output"), ("b", "ok")]


def test_a_refusal_is_final_and_recorded_and_the_next_route_is_not_asked() -> None:
    second = ScriptedMaker("b")
    inference, ledger = router(ScriptedMaker("a", error=ProviderRefused("blocked")), second)
    with pytest.raises(InferenceRefused):
        run(inference.make_image("a lamp", "square", **ASK))
    assert second.asked == []
    assert [(c.provider, c.outcome) for c in ledger.calls] == [("a", "refused")]


def test_when_every_route_fails_the_error_names_each_failure_kind_in_order() -> None:
    inference, _ = router(ScriptedMaker("a", error=failing("unavailable")),
                          ScriptedMaker("b", error=ProviderFailed("error", "HTTP status=400")))
    with pytest.raises(ImageUnavailable) as e:
        run(inference.make_image("a lamp", "square", **ASK))
    assert e.value.failures == ("unavailable", "error")


def test_a_provider_that_was_unavailable_rests_so_the_next_call_skips_it() -> None:
    first = ScriptedMaker("a", error=failing("unavailable"))
    inference, _ = router(first, ScriptedMaker("b"))
    run(inference.make_image("one", "square", **ASK))
    run(inference.make_image("two", "square", **ASK))
    assert first.asked == ["one"]


def test_a_household_at_its_limit_is_refused_before_any_provider_is_called() -> None:
    maker = ScriptedMaker("a")
    inference, ledger = router(maker, drawn=2, limit=2)
    with pytest.raises(ImageCapped) as e:
        run(inference.make_image("a lamp", "square", **ASK))
    assert (e.value.limit, maker.asked, ledger.calls) == (2, [], [])


def test_a_household_under_its_limit_draws() -> None:
    inference, _ = router(ScriptedMaker("a"), drawn=1, limit=2)
    assert run(inference.make_image("a lamp", "square", **ASK)).provider == "a"


def test_with_no_limit_wired_no_picture_is_drawn() -> None:
    maker = ScriptedMaker("a")
    inference, _ = router(maker, capped=False)
    with pytest.raises(ImageCapped):
        run(inference.make_image("a lamp", "square", **ASK))
    assert maker.asked == []


def test_a_blank_prompt_is_a_value_error_before_anything_is_called() -> None:
    maker = ScriptedMaker("a")
    inference, _ = router(maker)
    with pytest.raises(ValueError):
        run(inference.make_image("  ", "square", **ASK))
    assert maker.asked == []


def test_the_log_line_carries_the_provider_model_outcome_bytes_and_duration_and_never_the_prompt(
        caplog: pytest.LogCaptureFixture) -> None:
    inference, _ = router(ScriptedMaker("a"))
    with caplog.at_level(logging.INFO, logger="ashley.inference"):
        run(inference.make_image("a secret lamp", "wide", **ASK))
    record = next(r for r in caplog.records if r.getMessage() == "inference.call")
    fields: dict[str, object] = getattr(record, "fields")
    assert {k: fields[k] for k in ("task", "provider", "model", "outcome", "bytes", "aspect")} == {
        "task": "image", "provider": "a", "model": "a-model", "outcome": "ok", "bytes": len(JPEG), "aspect": "wide"}
    assert isinstance(fields["duration_ms"], int)
    assert "secret" not in "\n".join(f"{r.getMessage()} {getattr(r, 'fields', '')}" for r in caplog.records)

"""The hybrid recall eval's cases and report; the run itself needs the real model (`python -m ashley.evals
memory-recall-hybrid`)."""

from typing import Any

import pytest
from ashley.evals import memory_recall_hybrid
from ashley.evals.__main__ import parser
from ashley.memory.eval import hybrid
from ashley.memory.recall_policy import RecallPolicy


def test_the_cases_are_authored_and_cover_the_three_styles() -> None:
    data = hybrid.load()
    assert {c["source"] for c in data["cases"]} == {"authored"}
    assert {c["style"] for c in data["cases"]} == {"lexical", "paraphrase", "indirect"}
    assert len(data["nothing"]) > 0


def test_a_case_naming_a_fact_that_does_not_exist_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    data = hybrid.load()
    data["cases"][0]["relevant"] = ["nope"]

    def stale(text: str) -> dict[str, Any]:
        return data

    monkeypatch.setattr(hybrid.json, "loads", stale)
    with pytest.raises(ValueError, match="nope"):
        hybrid.load()


def test_the_report_shows_both_rates_per_style_and_the_command_is_registered() -> None:
    text = hybrid.Scored({"lexical": (3, 4), "paraphrase": (1, 4)}, 2.0, 1.0)
    both = hybrid.Scored({"lexical": (4, 4), "paraphrase": (3, 4)}, 5.0, 3.0)
    report = memory_recall_hybrid.render(text, both, RecallPolicy(10, 3))
    assert "paraphrase" in report and "1/4" in report and "3/4" in report and "4/8 50%" in report and "7/8" in report
    assert parser().parse_args(["memory-recall-hybrid"]).eval == "memory-recall-hybrid"

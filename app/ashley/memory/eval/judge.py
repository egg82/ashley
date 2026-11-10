"""The write harness's judge (`write.Judge`) by a model: one `memory_judge` call per comparison, through `Inference`,
and the controls that show whether its verdicts can be trusted."""

import json
from importlib import resources

from pydantic import BaseModel, ConfigDict, Field

from ... import services
from ...inference.inference import Inference
from ...inference.model import DEFAULT_VARIANT, Message, Prompt, SystemPrompt
from .write import Judge

SYSTEM = (
    "You compare two statements of a fact about a household. `same_fact` is true when the written statement says what "
    "the expected one says: the same people, the same thing, and the same particulars (times, days, numbers, places). "
    "Wording may differ, and it may add detail that does not contradict. It is false when the written statement leaves "
    "out or changes any particular of the expected one, or states something else. Name that particular in "
    "`missing_or_changed` first, or leave it empty when there is none; synonyms (bought and ordered, a present and a "
    "gift) are not a change."
)


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    missing_or_changed: str = Field(description="The expected statement's particular that the written one leaves out or "
                                                "changes; empty when there is none.")
    same_fact: bool


async def judge(expected: str, actual: str) -> bool:
    """Whether `actual` states the fact `expected` states. Raises InferenceUnavailable and InferenceRefused."""
    message = Message("person", f"Expected: {expected}\nWritten: {actual}")
    prompt = Prompt(system={DEFAULT_VARIANT: SystemPrompt(SYSTEM)}, messages=(message,))
    return (await services.get(Inference).generate("memory_judge", prompt, Verdict)).same_fact


async def failed_controls(verdict: Judge = judge) -> list[str]:
    """The controls in `judge_controls.json` that `verdict` gets wrong: pairs it must reject (a changed time, swapped
    people, a dropped particular) and paraphrases it must accept. Empty means its verdicts can be trusted."""
    data = json.loads(resources.files("ashley.memory.eval").joinpath("judge_controls.json").read_text("utf-8"))
    return [f"{c['written']!r} vs {c['expected']!r}: want same={c['same']}" for c in data["controls"]
            if await verdict(c["expected"], c["written"]) != c["same"]]

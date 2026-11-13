"""The bench replay's grader: one call per final answer of hers (task `eval_judge`), reading the ask, her answer and the
names of the bench's measurement rows, and answering in structured fields what only her words carry. Its verdicts are
kept apart from the measures the records give (`bench_replay_measures`); nothing in the product reads them.
`ScriptedGrader` stands in for it in the scripted mode, answering from the answer's length alone."""

from collections.abc import Sequence

from pydantic import BaseModel, Field

from .. import services
from ..inference.inference import Inference, InferenceError
from ..inference.model import Message, Prompt, SystemPrompt

INSTRUCTIONS = (
    "You grade one reply an assistant wrote on a shared design bench, where it builds 3D models for a person. You are "
    "given the person's message, the assistant's reply, and the names of the measurement rows the bench holds. Judge "
    "only what the reply's words say; do not judge whether the design is good. Fill each field from the reply alone.")


class Verdict(BaseModel):
    asks_to_look: bool = Field(description="The reply asks the person to look at, check or confirm something visually "
                                           "(a render, a model, a print, a photo) before it goes on.")
    asked_form: bool = Field(description="The reply asks what the real object the build must fit looks like (its shape, "
                                         "its cross-section, how it is made), or asks for a photo of it.")
    claims_done: bool = Field(description="The reply says the change the person asked for is now made, built or fixed.")
    asked_rows: list[str] = Field(description="The measurement row names, from the list given, whose value the reply "
                                              "asks the person to give or confirm. Empty when it asks for none.")
    asked_other: int = Field(ge=0, description="How many other facts, not in the list given, the reply asks "
                                               "the person to give or confirm.")


def prompt(ask: str, answer: str, row_names: Sequence[str]) -> Prompt:
    listed = ", ".join(row_names) if row_names else "(none)"
    said = f"The person's message:\n{ask}\n\nThe assistant's reply:\n{answer}\n\nMeasurement rows on the bench: {listed}"
    return Prompt({"default": SystemPrompt(INSTRUCTIONS)}, (Message("person", said),))


async def grade(ask: str, answer: str, row_names: Sequence[str]) -> Verdict | None:
    """The verdict, its rows narrowed to the names given; None when no grader answered."""
    try:
        got = await services.get(Inference).generate("eval_judge", prompt(ask, answer, row_names), Verdict)
    except InferenceError:
        return None
    return got.model_copy(update={"asked_rows": [r for r in got.asked_rows if r in row_names]})


class ScriptedGrader:
    """Says an answer claims the change is made, and asks for the first row, when it is longer than `long` characters."""

    def __init__(self, long: int = 3) -> None:
        self._long = long

    async def __call__(self, ask: str, answer: str, row_names: Sequence[str]) -> Verdict | None:
        said = len(answer) > self._long
        return Verdict(asks_to_look=False, asked_form=False, claims_done=said,
                       asked_rows=list(row_names[:1]) if said else [], asked_other=0)

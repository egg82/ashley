"""The wire models of `/api/outside-actions`."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel


class OutsideAction(BaseModel):
    """A change she made for the signed-in person with no OK, in a turn that had read words written outside the
    household. `label` is the plain headline the person was shown for it, None for one made before headlines were kept;
    `summary` is code's plain-words account of the change, never her words. `tier`: `runs`, a kind of change that always
    runs on its own; `judged`, one the action judge let run. `explanation` is the judge's reason in words, None for
    `runs` and for a judged one that kept none."""

    id: int
    label: str | None
    summary: str
    tier: Literal["runs", "judged"]
    explanation: str | None
    at: AwareDatetime


class OutsideActionsResponse(BaseModel):
    """The signed-in person's most recent outside actions, as `outside_actions`, newest first, at most `limit` of them. Rows are kept 90 days.
    Only theirs: another person's, or another household's, are never listed."""

    outside_actions: list[OutsideAction]

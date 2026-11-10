"""What code shows beside a turn, as a value: the shape `tools` builds and `conversations` stores. A leaf module so
neither imports the other."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, get_args

AgreedStatus = Literal["ran", "failed", "not_run"]
_STATUSES: dict[str, AgreedStatus] = {s: s for s in get_args(AgreedStatus)}


@dataclass(frozen=True)
class Receipt:
    """One change code shows beside her reply: `headline` is the tool's plain label, `detail` code's own summary of the
    call (None where the reply was shared), `why` the judge's reason when there is one."""

    headline: str
    detail: str | None = None
    why: str | None = None

    def to_json(self) -> dict[str, str | None]:
        return {"headline": self.headline, "detail": self.detail, "why": self.why}

    @staticmethod
    def from_json(raw: Mapping[str, Any]) -> "Receipt":
        """The inverse of `to_json`. Raises KeyError when `headline` is missing."""
        detail, why = raw.get("detail"), raw.get("why")
        return Receipt(str(raw["headline"]), None if detail is None else str(detail), None if why is None else str(why))


@dataclass(frozen=True)
class Receipts:
    """What code shows beside a tainted turn's answer, kept with her turn and never part of her words: `done` the
    changes the action judge let run, `held` the calls waiting for the person's OK, in the order made. At least one is
    non-empty; `proposal_id` is the held proposal, set exactly when `held` is non-empty. Raises ValueError otherwise."""

    done: tuple[Receipt, ...] = ()
    held: tuple[Receipt, ...] = ()
    proposal_id: int | None = None

    def __post_init__(self) -> None:
        if not self.done and not self.held:
            raise ValueError("receipts show something")
        if bool(self.held) != (self.proposal_id is not None):
            raise ValueError("a proposal is named exactly when something is held")

    def to_json(self) -> dict[str, object]:
        return {"done": [r.to_json() for r in self.done], "held": [r.to_json() for r in self.held],
                "proposal_id": self.proposal_id}

    @staticmethod
    def from_json(raw: Mapping[str, Any]) -> "Receipts":
        """The inverse of `to_json`. Raises KeyError for a missing key, ValueError for receipts that show nothing."""
        return Receipts(tuple(Receipt.from_json(r) for r in raw["done"]), tuple(Receipt.from_json(r) for r in raw["held"]),
                        raw["proposal_id"])


@dataclass(frozen=True)
class AgreedCall:
    """One held call the person agreed to: its `summary` as they were shown it, and whether it `ran`, `failed` (the tool
    answered with an error) or was `not_run` (the tool is not offered now). Never what the call returned."""

    summary: str
    status: AgreedStatus


@dataclass(frozen=True)
class AgreedOutcome:
    """What became of a held proposal the person agreed to, kept with their agreeing turn and shown beside it, never as
    her words: each call in the order it was held, or `interrupted` when the runner carrying them out stopped partway,
    so any of them may or may not have taken effect and none is known. Raises ValueError for calls on an interrupted
    outcome."""

    calls: tuple[AgreedCall, ...] = ()
    interrupted: bool = False

    def __post_init__(self) -> None:
        if self.interrupted and self.calls:
            raise ValueError("an interrupted outcome knows no call")

    def to_json(self) -> dict[str, object]:
        return {"calls": [{"summary": c.summary, "status": c.status} for c in self.calls],
                "interrupted": self.interrupted}

    @staticmethod
    def from_json(raw: Mapping[str, Any]) -> "AgreedOutcome":
        """The inverse of `to_json`. Raises KeyError for a missing key or an unknown status."""
        return AgreedOutcome(tuple(AgreedCall(str(c["summary"]), _STATUSES[c["status"]]) for c in raw["calls"]),
                             bool(raw["interrupted"]))

"""The memory writer's output, and the ops it becomes. Pydantic is the one source: the type, its validator and the JSON
Schema the model is sent. Code checks what it can: a target that is not a known fact, or a person who is not in the
household, drops the op rather than guess at it."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..conversations.model import Turn
from ..text import Cleaned
from .model import Add, Forget, Invalidate, Kind, NewFact, Noop, Op, Update, Visibility

OpKind = Literal["add", "update", "invalidate", "forget", "noop"]
_FACT_OPS: tuple[OpKind, ...] = ("add", "update")


class WrittenOp(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    op: OpKind
    target: int | None = Field(description="The id of the known fact this op is about; null for an add.")
    about: int | None = Field(description="The id of the person the fact is about; null for the household.")
    owner: int | None = Field(description="The id of the person whose fact it is to share or forget; null for the "
                                          "household.")
    visibility: Visibility
    visibility_stated: bool = Field(description="True only when the owner said who may know.")
    kind: Kind
    standing: bool = Field(description="True when it is true of someone for good and changes what a good reply looks "
                                       "like without being mentioned.")
    text: Cleaned = Field(description="One self-contained statement of the fact; empty unless add or update.")
    source_turn: int | None = Field(description="The id of the turn in the conversation the fact came from; null "
                                                "unless add or update.")


class Written(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ops: tuple[WrittenOp, ...]


@dataclass(frozen=True)
class Converted:
    """The ops kept, in the order written, how many were dropped for each reason, and how many facts had their source
    turn or owner replaced."""

    ops: tuple[Op, ...]
    unknown_target: int
    unknown_person: int
    empty_text: int
    turn_fallback: int
    owner_cleared: int


def to_ops(written: Written, known: Collection[int], people: Collection[int], turns: Sequence[Turn]) -> Converted:
    """Each written op as an `Op`. An `update`, `invalidate` or `forget` whose `target` is not in `known` is dropped,
    as is a `noop` naming such a target; an `add` or `update` whose `about` or `owner` is neither null nor in `people`,
    or whose `text` is blank, is dropped. An `add` ignores `target`; the other ops ignore the fact fields.

    A fact keeps its `source_turn` only when it is one of `turns`, the turns the writer was shown; otherwise it takes
    the last person turn of `turns` (None when there is none), and `turn_fallback` counts those.

    An added household fact (`about` null) has no owner unless `visibility_stated`: only someone who said who may know
    it keeps it as theirs. A written owner on any other added household fact is cleared, and `owner_cleared` counts
    those. An `update` keeps the owner written, since a person may have made a household fact theirs."""
    reasons = [_dropped(w, known, people) for w in written.ops]
    kept = [w for w, reason in zip(written.ops, reasons) if reason is None]
    shown = {t.id for t in turns}
    fallback = next((t.id for t in reversed(turns) if t.author == "person"), None)
    ops = tuple(_op(w, w.source_turn if w.source_turn in shown else fallback) for w in kept)
    missed = sum(w.op in _FACT_OPS and w.source_turn not in shown for w in kept)
    cleared = sum(w.op == "add" and w.owner is not None and _owner(w) is None for w in kept)
    return Converted(ops, reasons.count("unknown_target"), reasons.count("unknown_person"), reasons.count("empty_text"),
                     missed, cleared)


def _dropped(w: WrittenOp, known: Collection[int], people: Collection[int]) -> str | None:
    """Why `w` cannot be kept, or None."""
    if w.op != "add" and (w.target not in known if w.target is not None else w.op != "noop"):
        return "unknown_target"
    if w.op in _FACT_OPS and any(p is not None and p not in people for p in (w.about, w.owner)):
        return "unknown_person"
    if w.op in _FACT_OPS and not w.text.strip():
        return "empty_text"
    return None


def _op(w: WrittenOp, source_turn: int | None) -> Op:
    match w.op:
        case "add":
            return Add(_fact(w, source_turn))
        case "update":
            return Update(_target(w), _fact(w, source_turn))
        case "invalidate":
            return Invalidate(_target(w))
        case "forget":
            return Forget(_target(w))
        case "noop":
            return Noop(w.target)


def _target(w: WrittenOp) -> int:
    if w.target is None:
        raise ValueError(f"a {w.op} needs a target")
    return w.target


def _fact(w: WrittenOp, source_turn: int | None) -> NewFact:
    return NewFact(about_id=w.about, owner_id=_owner(w), visibility=w.visibility, visibility_stated=w.visibility_stated,
                   kind=w.kind, standing=w.standing, text=w.text.strip(), source_turn_id=source_turn)


def _owner(w: WrittenOp) -> int | None:
    return w.owner if w.op != "add" or w.about is not None or w.visibility_stated else None

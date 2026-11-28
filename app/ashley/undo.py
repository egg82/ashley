"""How a change she made is taken back, as a value: the shape a tool sets on its result (`ToolResult.undo`) and
`senses.outside_record` keeps beside the change. A leaf module so neither `inference` nor `senses` imports the other."""

from dataclasses import dataclass
from typing import Literal, get_args

UndoKind = Literal["house_delete", "reminder_cancel", "todo_remove", "todo_done", "todo_reopen"]
"""The inverse to carry out: `house_delete` deletes the config or record `ref` of the house kind `within` (an
automation, script or helper she created, or an area, floor or label); `reminder_cancel` cancels the reminder whose
wake id is `ref`; `todo_remove`, `todo_done` and `todo_reopen` make that change to the item `ref` (its id, else its
exact text) of the to-do list `within`."""


@dataclass(frozen=True)
class Undo:
    """What takes one change back: `kind`, the record `ref` it acts on and the place `within` it, None where `kind`
    needs none. A change with no inverse (a send, a delete, a replaced config, a moved mail) has no `Undo` at all."""

    kind: UndoKind
    ref: str
    within: str | None = None


def undo_of(kind: str | None, ref: str | None, within: str | None) -> Undo | None:
    """The stored fields as an `Undo`; None when no kind is stored, or a kind this release does not know."""
    for known in get_args(UndoKind):
        if known == kind and ref is not None:
            return Undo(known, ref, within)
    return None

"""A change to the house as data: what she asks `house_change` for, what a proposal keeps for a person's OK, and what
carries it out on a `House`. Its operation key (`house.py`) is what `irreversible` judges; nothing else decides whether
it needs the person first."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from .house import CONFIG_KINDS, RECORD_KINDS, House, HouseRejected, config_kind, record_kind

Op = Literal["write", "create", "update", "delete", "perform"]
OPS: tuple[Op, ...] = ("write", "create", "update", "delete", "perform")
KINDS: tuple[str, ...] = (*CONFIG_KINDS, *RECORD_KINDS, "action")


@dataclass(frozen=True)
class Change:
    """`op` on a `kind`: `write` a config (automation, script, helper), `create` an area, floor or label, `update` a
    record's fields, `delete` a config or record (removing an integration), or `perform` an action. `id` names what
    it is on (a config id or record id; the action's name for `perform`), `data` the config, fields or action data,
    `ids` the things a `perform` acts on."""

    op: Op
    kind: str
    id: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict[str, Any])
    ids: tuple[str, ...] = ()

    def key(self) -> str:
        """The operation key `irreversible.json` is matched against."""
        if self.op == "perform":
            return f"perform:{self.id}"
        if self.op == "delete" and self.kind == "integration":
            return "remove:integration"
        scope = "config" if self.kind in CONFIG_KINDS else "record"
        return f"{self.op}:{scope}:{self.kind}"


def check(change: Change) -> None:
    """Raises ValueError, naming only the argument, when the change is not a well-formed one: the kind must suit the op."""
    if change.kind not in KINDS:
        raise ValueError(f"kind is one of {', '.join(KINDS)}")
    fits = {"write": change.kind in CONFIG_KINDS, "create": change.kind in ("area", "floor", "label"),
            "update": change.kind in RECORD_KINDS and change.kind != "integration",
            "delete": change.kind in (*CONFIG_KINDS, *RECORD_KINDS),
            "perform": change.kind == "action"}
    if not fits[change.op]:
        raise ValueError(f"a {change.op} does not apply to a {change.kind}")
    if change.op in ("update", "delete") and not change.id:
        raise ValueError(f"a {change.op} names the id it is on")
    if change.op == "perform" and not (change.id and "." in change.id):
        raise ValueError("a perform's id is the action, domain.name")


def op_of(op: str) -> Op | None:
    """`op` as an Op; None when it is not one."""
    return next((o for o in OPS if o == op), None)


async def carry_out(house: House, change: Change) -> str:
    """Do `change` on `house`; a short result for her (an id, or what was removed), never the change's contents. Raises
    HouseRejected when the house refuses it or there is nothing to change, HouseUnavailable."""
    config, record = config_kind(change.kind), record_kind(change.kind)
    if change.op == "perform":
        done = await house.perform(str(change.id), change.ids, change.data)
        return f"{len(done.changed)} changed"
    if change.op == "write" and config is not None:
        return await house.write_config(config, change.id, change.data)
    if change.op == "create" and record is not None:
        return await house.create_record(record, change.data)
    if change.op == "update" and record is not None:
        await house.update_record(record, str(change.id), change.data)
        return str(change.id)
    if change.op == "delete" and config is not None:
        if not await house.delete_config(config, str(change.id)):
            raise HouseRejected(f"there is no {change.kind} with that id")
        return str(change.id)
    if change.op == "delete" and record is not None:
        await house.delete_record(record, str(change.id))
        return str(change.id)
    raise HouseRejected(f"a {change.op} does not apply to a {change.kind}")

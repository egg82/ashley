"""A screen tool's arguments, as the model sent them, made into Workshop Commands by her. Which kinds exist, and how long
a body may be, are `decide`'s to judge; this checks only shapes."""

from collections.abc import Mapping

from ..tools.bench_args import BadArguments, piece_id_of
from ..tools.bench_args import command_of as bench_command_of
from ..tools.tainted import her
from ..workshop.commands import Add, Edit, Move, Remove, Undo
from ..workshop.json_shape import list_of, object_of
from ..workshop.model import Text
from ..workshop.rules import Rules
from ..workshop.screen_controls import ACTIONS, Control, encode
from .kiosk.controls import Wanted, validate


def device_of(args: Mapping[str, object]) -> int | None:
    """The optional `device_id`, None when absent. Raises BadArguments."""
    if "device_id" not in args:
        return None
    value = args["device_id"]
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int) or isinstance(value, bool):
        raise BadArguments("device_id is a whole number")
    return value


def add_of(args: Mapping[str, object], rules: Rules) -> Add:
    """`screen_add`'s Add: last, the kind's label as its title, an empty body (a controls piece holds an empty list)."""
    kind = args.get("kind")
    if not isinstance(kind, str):
        raise BadArguments("kind is a string")
    made = bench_command_of("bench_add", {"kind": kind, "title": _label(kind, rules), "body": _empty_body(kind, rules),
                                          "size": args.get("size", "medium")})
    assert isinstance(made, Add)
    return made


def move_of(args: Mapping[str, object]) -> Move:
    made = bench_command_of("bench_move", {"piece_id": args.get("piece_id"), "order": args.get("order"),
                                           "size": args.get("size")})
    assert isinstance(made, Move)
    return made


def remove_of(args: Mapping[str, object]) -> Remove:
    return Remove(her(), piece_id_of(args))


def undo_of(seq: int) -> Undo:
    return Undo(her(), seq)


def buttons_of(args: Mapping[str, object], domains: Mapping[str, str], rules: Rules) -> tuple[Edit, tuple[Control, ...]]:
    """`screen_buttons`' Edit of the controls piece, and the controls it holds. Raises BadArguments, and ControlRefused
    for a list the house's catalogue (`domains`) or the limits do not allow."""
    listed = list_of(args.get("buttons"))
    if listed is None:
        raise BadArguments("buttons is a list")
    wanted = [_wanted(item) for item in listed]
    controls = validate(wanted, domains)
    base = args.get("base_version")
    if not isinstance(base, int) or isinstance(base, bool):
        raise BadArguments("base_version is a whole number")
    return Edit(her(), piece_id_of(args), base, Text(rules.kinds["controls"].label, encode(controls))), controls


def _wanted(item: object) -> Wanted:
    fields = object_of(item) or {}
    ident, label, action, entity = (fields.get(k) for k in ("id", "label", "action", "entity_id"))
    if not isinstance(label, str) or not isinstance(entity, str) or not (ident is None or isinstance(ident, str)):
        raise BadArguments("each button is an id (or none), a label, an action and an entity_id, all strings")
    if not isinstance(action, str) or action not in ACTIONS:
        raise BadArguments("action is one of " + ", ".join(ACTIONS))
    return Wanted(ident, label, ACTIONS[action], entity)


def _label(kind: str, rules: Rules) -> str:
    known = rules.kinds.get(kind)
    return known.label if known is not None else kind


def _empty_body(kind: str, rules: Rules) -> str:
    known = rules.kinds.get(kind)
    return "[]" if known is not None and known.format == "controls" else ""


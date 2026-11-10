"""Her Home Assistant automation tools on a bench, as the model is offered them (`bench_automations`)."""

from collections.abc import Mapping

from ..inference.model import ToolSpec
from ..workshop import wake_action

LIST, READ, PROPOSE, STATE = "house_automations", "house_automation", "bench_propose_install", "bench_install_state"
INSTRUCTIONS = (
    "On this bench you can work out Home Assistant automations with the person. house_automations lists the house's "
    "automations; house_automation reads one's config, to bring it onto the bench as a piece of kind automation "
    "with the body it gives. An automation piece's body is Home Assistant's automation config as one JSON object "
    "(alias, description, triggers, conditions, actions, mode). Nothing on the bench changes the house: when you and "
    "the person agree a piece is ready, propose installing it with bench_propose_install (enabled or not, and an old "
    "automation it replaces to turn off), and the person approves it on the piece. bench_install_state says whether "
    "it is waiting on them and how the latest install went.")

WAKE_ACTION = (
    "An automation that should wake you carries one action: {\"action\": \"" + wake_action.SERVICE + "\", \"data\": "
    "{\"event\": <a slug, the event a wake piece answers>, \"event_id\": \"{{ context.id }}\", optionally \"who\": "
    "<a person.* entity id or one template>, \"what\": <a slug or one template>, \"when\": <one template>}} and no other "
    "keys; any other shape is refused as bad_automation. ")
WIRED = "This house has " + wake_action.SERVICE + " set up, so that action reaches you."
NOT_WIRED = ("This house does not have " + wake_action.SERVICE + " set up in Home Assistant yet, so that action "
             "would reach nothing until it is; say so once, and do not ask the person how it works.")
UNKNOWN = "Whether this house has " + wake_action.SERVICE + " set up could not be read just now; do not ask the person."
LOOK_FIRST = ("Before you ask the person about the house's setup (its devices, automations, what exists, how something "
              "is wired), look it up with your house tools; ask only what the house cannot tell you, such as "
              "preferences and routines.")


def instructions(wired: bool | None) -> str:
    """The guidance for her automation tools, with what the house says about the wake action."""
    state = UNKNOWN if wired is None else WIRED if wired else NOT_WIRED
    return f"{INSTRUCTIONS} {WAKE_ACTION}{state} {LOOK_FIRST}"


_INT: Mapping[str, object] = {"type": "integer"}


def _object(properties: Mapping[str, object], required: tuple[str, ...]) -> Mapping[str, object]:
    return {"type": "object", "properties": dict(properties), "required": list(required)}


SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(LIST, "List the house's automations: each one's id (null for one Home Assistant cannot edit), entity id, "
             "name, whether it is enabled and when it last fired.", _object({}, ()), reads=True, outside=False),
    ToolSpec(READ, "Read one automation's config by its id, as the body of an automation piece.",
             _object({"automation_id": {"type": "string"}}, ("automation_id",)), reads=True, outside=False),
    ToolSpec(PROPOSE, "Propose installing an automation piece of this bench, as it is at the version you read, into "
             "Home Assistant. Nothing changes until the person approves it on the piece. `enabled`: whether it runs "
             "once installed; `turn_off`: the entity id of an automation it replaces, turned off with it.",
             _object({"piece_id": _INT, "base_version": _INT, "enabled": {"type": "boolean"},
                      "turn_off": {"type": "string"}}, ("piece_id", "base_version", "enabled")), outside=False, tier="judged"),
    ToolSpec(STATE, "Whether an automation piece's install is waiting on the person's approval, and what its latest "
             "install, or undo of one, did to the house.", _object({"piece_id": _INT}, ("piece_id",)), reads=True, outside=False),
)

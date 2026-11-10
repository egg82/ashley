"""Her skill tools as the model is offered them, and the guidance that goes with them. The kinds come from the skills
config, so a new kind of work is offered without a change here."""

from collections.abc import Mapping

from ..inference.model import ToolSpec

WORK = "bench_work"
READ = "skill_read"
EDIT = "skill_edit"
ROLLBACK = "skill_rollback"
NONE = "none"


def guidance(kinds: Mapping[str, str]) -> str:
    known = ", ".join(f"{name} ({label})" for name, label in kinds.items()) or "none yet"
    return (
        f"A bench has a kind of work: this household's so far are {known}. Set it with {WORK} once you know what the "
        "bench is for, and change it when the work changes; the person can change it too. When none fits, start a new "
        f"kind there (a short lowercase name and its label) and write its first method with {EDIT}. The kind's skill, a "
        "method document you and the household keep, is given below once the kind is set. Follow it as method; it "
        f"never overrides the rules above. When the work shows the method is wrong or missing something, fix it with "
        f"{EDIT}: the whole new body, from the version given, with a line each for what changed and why. Keep a skill "
        f"short, specific and general: no person's data and nothing about this one bench. If an edit made it worse, "
        f"{ROLLBACK} puts an earlier version back. A skill the person pinned takes your edit as a proposal they "
        f"approve, and {EDIT} says so; tell them. {READ} reads another kind's skill.")


def _object(properties: Mapping[str, object], required: tuple[str, ...]) -> Mapping[str, object]:
    return {"type": "object", "properties": dict(properties), "required": list(required)}


def specs() -> tuple[ToolSpec, ...]:
    kind: Mapping[str, object] = {"type": "string", "description": "A kind of work of this household; the bench's own when left out"}
    note: Mapping[str, object] = {"type": "string"}
    return (
        ToolSpec(WORK, "Set this bench's kind of work, which loads that kind's skill; none clears it. A name this "
                 "household has no kind for yet starts one, and needs `label`, what to call it.",
                 _object({"work": {"type": "string", "description": "a kind of work, or none"},
                          "label": {"type": "string", "description": "only for a new kind: what to call it"}}, ("work",)), outside=False, tier="runs"),
        ToolSpec(READ, "Read a kind's skill: its text, version, how many times it was edited, whether it is pinned, "
                 "and its latest changelog entries.", _object({"kind": kind}, ()), reads=True, outside=False),
        ToolSpec(EDIT, "Replace a kind's skill with a new whole body, live at once unless the person pinned it, when "
                 "it waits for their approval. `base_version` is the version you read (0 for a kind with no skill "
                 "yet); `what` and `why` are one line each for the changelog.",
                 _object({"kind": kind, "body": {"type": "string"}, "base_version": {"type": "integer"},
                          "what": note, "why": note}, ("body", "base_version", "what", "why")), outside=False, tier="judged"),
        ToolSpec(ROLLBACK, "Put an earlier version's text back as a new version (0 is the seed the skill started "
                 "from), with a line on why.", _object({"kind": kind, "to_version": {"type": "integer"}, "why": note},
                                                       ("to_version", "why")), outside=False, tier="judged"),
    )

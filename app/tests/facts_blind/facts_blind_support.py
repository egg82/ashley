"""Shared pieces of the choice-row blind contract tests (design: `facts-design/design.md` sections 1 and 2): builders
for a choice row and a body of rows, and the real `decide` driven with the shipped rules."""

import json
from typing import Any

from ashley.workshop.commands import Add, Edit
from ashley.workshop.decide import EMPTY, Accepted, BenchState, Decision, Refused, decide
from ashley.workshop.measurements import well_formed
from ashley.workshop.model import HER, By, Text
from ashley.workshop.rules import Rules, load

RULES: Rules = load()
ALANA = By(7)
KIND = "measurements"
STATED_SOURCES = ("stated", "accepted")
CITED_PIECE_SOURCES = ("seen", "datasheet")
CHOICE_SOURCES = (*STATED_SOURCES, *CITED_PIECE_SOURCES, "guessed")
REFUSED_SOURCES = ("bound", "measured")

NUMBER: dict[str, Any] = {"name": "width", "value": 12.5, "unit": "mm", "source": "measured"}
CHOICE: dict[str, Any] = {"kind": "choice", "name": "lanyard_form", "label": "The lanyard", "value": "flat woven strap",
                          "source": "guessed"}


def choice(**changes: object) -> dict[str, Any]:
    """A well-formed guessed choice row with the given keys replaced; a key set to None is dropped."""
    row = {**CHOICE, **changes}
    return {k: v for k, v in row.items() if v is not None}


def cited(source: str, **changes: object) -> dict[str, Any]:
    """A well-formed choice row of `source` carrying the citation that source needs: a turn, or a piece (id 2)."""
    cite: dict[str, object] = {"turn": 41} if source in STATED_SOURCES else {"piece": 2} if source in CITED_PIECE_SOURCES else {}
    return choice(source=source, **{**cite, **changes})


def body_of(*items: object) -> str:
    return json.dumps({"items": list(items)})


def ok(*items: object) -> bool:
    return well_formed(body_of(*items))


def decide_add(body: str, by: By = HER, state: BenchState = EMPTY) -> Decision:
    return decide(state, Add(by, KIND, Text("facts", body), "small"), RULES)


def decide_edit(state: BenchState, piece_id: int, version: int, body: str, by: By = HER) -> Decision:
    return decide(state, Edit(by, piece_id, version, Text("facts", body)), RULES)


def accepted(decision: Decision) -> Accepted:
    if isinstance(decision, Refused):
        raise AssertionError(f"refused {decision.reason}")
    return decision


def refused_as(decision: Decision) -> str:
    assert isinstance(decision, Refused), "was accepted"
    return decision.reason


def bench_with_site() -> BenchState:
    """A bench holding one site piece (id 1) and then one measurements piece (id 2), both by the person."""
    state = accepted(decide(EMPTY, Add(ALANA, "site", Text("page", "https://example.com/strap"), "small"), RULES)).state
    return accepted(decide(state, Add(ALANA, KIND, Text("facts", ""), "small"), RULES)).state

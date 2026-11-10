"""The diagram kind through `decide`: Mermaid source is stored as written, up to the kind's length, and runs nothing."""

from ashley.workshop import rules
from ashley.workshop.commands import Add, Edit, Run
from ashley.workshop.decide import Accepted, Refused, replay
from ashley.workshop.model import By, Text

ALANA = By(7)
RULES = rules.load()
SOURCE = "flowchart TD\n  A[Start] --> B{Ready?}\n  B -->|yes| C[Go]"


def last(*commands: Add | Edit | Run) -> object:
    return replay(commands, RULES)[-1]


def add(body: str) -> Add:
    return Add(ALANA, "diagram", Text("t", body), "medium")


def test_the_kind_is_stored_and_says_its_format() -> None:
    kind = RULES.kinds["diagram"]
    assert (kind.family, kind.format, kind.language) == ("stored", "diagram", None)


def test_mermaid_source_is_accepted_on_add_and_edit() -> None:
    assert isinstance(last(add(SOURCE)), Accepted)
    assert isinstance(last(add(""), Edit(ALANA, 1, 1, Text("t", SOURCE))), Accepted)


def test_a_body_at_the_length_is_accepted_and_one_over_is_too_long() -> None:
    limit = RULES.kinds["diagram"].max_chars
    assert isinstance(last(add("x" * limit)), Accepted)
    got = last(add("x" * (limit + 1)))
    assert isinstance(got, Refused) and got.reason == "too_long"
    got = last(add(""), Edit(ALANA, 1, 1, Text("t", "x" * (limit + 1))))
    assert isinstance(got, Refused) and got.reason == "too_long"


def test_a_diagram_is_not_runnable() -> None:
    got = last(add(SOURCE), Run(ALANA, 1, 1, "python"))
    assert isinstance(got, Refused) and got.reason == "not_runnable"

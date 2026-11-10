"""Planted `FactWriter`s for the Memory eval's tests: a control that returns each case's expected ops, built from the
file, and copies that each break one decision. The write cases are proven able to fail by the mutants that fail them."""

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any

from ashley.conversations.model import Conversation
from ashley.memory.eval import write
from ashley.memory.memory import FactWriter
from ashley.memory.model import Add, Fact, Forget, Invalidate, NewFact, Noop, Op, Update


def _person(people: dict[str, int], name: str | None) -> int | None:
    return None if name is None else people[name]


def _op(expected: dict[str, Any], people: dict[str, int], ids: dict[str, int], fold: bool = False) -> Op:
    kind = expected["op"]
    if kind == "invalidate":
        return Invalidate(ids[expected["target"]])
    if kind == "forget":
        return Forget(ids[expected["target"]])
    fact = NewFact(
        about_id=_person(people, expected["about"]),
        owner_id=_person(people, expected["owner"]) if "owner" in expected else None,
        visibility=expected.get("visibility", "shared"),
        visibility_stated=expected.get("visibility_stated", False),
        kind=expected.get("kind", "other"),
        standing=expected.get("standing", False),
        text=expected["states"] + (f", and {expected['omits']}" if fold and "omits" in expected else ""),
    )
    return Add(fact) if kind == "add" else Update(ids[expected["target"]], fact)


async def same_text(expected: str, actual: str) -> bool:
    """A judge for the planted writers, which state what each case expects word for word: like the model judge, it
    accepts a statement that adds to the expected one."""
    return expected in actual


class ExpectedWriter(FactWriter):
    """The control: the ops each case expects, found by the conversation's turns. With `fold`, each fact also states
    what its case expects it to omit."""

    def __init__(self, fold: bool = False) -> None:
        data = write.load()
        self.by_turns: dict[tuple[str, ...], tuple[Op, ...]] = {}
        for case in data["cases"]:
            conversation, _, ids = write.build(data, case)
            self.by_turns[tuple(t.text for t in conversation.turns)] = tuple(
                _op(e, data["people"], ids, fold) for e in case["expect"]
            )

    async def decide(self, conversation: Conversation, known: Sequence[Fact], now: datetime) -> tuple[Op, ...]:
        return self.by_turns[tuple(t.text for t in conversation.turns)] or (Noop(None),)


class Mutant(FactWriter):
    """The control with `change` applied to the ops it returns."""

    def __init__(self, change: Callable[[tuple[Op, ...]], tuple[Op, ...]]) -> None:
        self.control, self.change = ExpectedWriter(), change

    async def decide(self, conversation: Conversation, known: Sequence[Fact], now: datetime) -> tuple[Op, ...]:
        return self.change(await self.control.decide(conversation, known, now))


def _on_facts(edit: Callable[[NewFact], NewFact]) -> Callable[[tuple[Op, ...]], tuple[Op, ...]]:
    def change(ops: tuple[Op, ...]) -> tuple[Op, ...]:
        return tuple(
            Add(edit(o.fact)) if isinstance(o, Add) else Update(o.target, edit(o.fact)) if isinstance(o, Update) else o
            for o in ops
        )
    return change


def _each(edit: Callable[[Op], Op]) -> Callable[[tuple[Op, ...]], tuple[Op, ...]]:
    return lambda ops: tuple(edit(o) for o in ops)


def _update_as_add(op: Op) -> Op:
    return Add(op.fact) if isinstance(op, Update) else op


def _forget_as_invalidate(op: Op) -> Op:
    return Invalidate(op.target) if isinstance(op, Forget) else op


def _invalidate_as_forget(op: Op) -> Op:
    return Forget(op.target) if isinstance(op, Invalidate) else op


def _wrong_target(op: Op) -> Op:
    if isinstance(op, Update):
        return Update(op.target + 1, op.fact)
    return type(op)(op.target + 1) if isinstance(op, (Invalidate, Forget)) else op


def _invents_a_fact(ops: tuple[Op, ...]) -> tuple[Op, ...]:
    if any(not isinstance(o, Noop) for o in ops):
        return ops
    return (Add(NewFact(None, None, "shared", False, "other", False, "A thing that was only said in passing")),)


def _household_owned_by_alana(fact: NewFact) -> NewFact:
    return replace(fact, owner_id=1) if fact.about_id is None and fact.owner_id is None else fact


WRITE_MUTANTS: dict[str, Callable[[], FactWriter]] = {
    "always noop": lambda: Mutant(lambda ops: (Noop(None),)),
    "add instead of update": lambda: Mutant(_each(_update_as_add)),
    "invalidate instead of forget": lambda: Mutant(_each(_forget_as_invalidate)),
    "forget instead of invalidate": lambda: Mutant(_each(_invalidate_as_forget)),
    "wrong target": lambda: Mutant(_each(_wrong_target)),
    "everything shared": lambda: Mutant(_on_facts(lambda f: replace(f, visibility="shared"))),
    "ignores visibility_stated": lambda: Mutant(_on_facts(lambda f: replace(f, visibility_stated=False))),
    "drops the owner": lambda: Mutant(_on_facts(lambda f: replace(f, owner_id=None))),
    "wrong kind": lambda: Mutant(_on_facts(lambda f: replace(f, kind="other"))),
    "wrong subject": lambda: Mutant(_on_facts(lambda f: replace(f, about_id=None))),
    "states something else": lambda: Mutant(_on_facts(lambda f: replace(f, text="Something else entirely"))),
    "writes jokes and hypotheticals": lambda: Mutant(_invents_a_fact),
    "a household fact is its teller's": lambda: Mutant(_on_facts(_household_owned_by_alana)),
    "folds the one-off ask into the fact": lambda: ExpectedWriter(fold=True),
}

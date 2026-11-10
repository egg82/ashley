"""Planted implementations of `Memory` for the eval's tests: a correct in-memory one (the control, test-only) and
copies that each break one rule. The recall cases are proven able to fail by the mutants that fail them."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime

from ashley.conversations.model import Conversation, Kind as ConversationKind
from ashley.memory.memory import Memory
from ashley.memory.model import Add, Asker, Fact, Forget, Held, Invalidate, NewFact, Op, Recalled, Unwritten, Update


class RuleMemory(Memory):
    """The control: applies every rule of `Memory`'s contract. Each rule is a hook a mutant overrides. Retrieval
    ranking is not what the cases test, so `recall` returns every fact the rules allow."""

    def __init__(self) -> None:
        self.rows: dict[int, Fact] = {}

    def in_household(self, fact: Fact, asker: Asker) -> bool:
        return fact.household_id == asker.household_id

    def is_current(self, fact: Fact) -> bool:
        return fact.valid_to is None

    def visible(self, fact: Fact, asker: Asker) -> bool:
        if fact.visibility != "private":
            return fact.visibility == "shared" or asker.speaker_id is not None
        return asker.owner_only and asker.speaker_id is not None and fact.owner_id == asker.speaker_id

    def volunteerable(self, fact: Fact, asker: Asker) -> bool:
        return fact.visibility == "shared" or fact.owner_id == asker.speaker_id

    async def recall(self, asker: Asker, query: str) -> tuple[Recalled, ...]:
        return tuple(
            Recalled(f, self.volunteerable(f, asker))
            for f in self.rows.values()
            if self.in_household(f, asker) and self.is_current(f) and self.visible(f, asker) and not f.standing
        )

    async def profile(self, asker: Asker) -> tuple[Recalled, ...]:
        return tuple(
            Recalled(f, self.volunteerable(f, asker))
            for f in self.rows.values()
            if self.in_household(f, asker) and self.is_current(f) and self.visible(f, asker) and f.standing
        )

    def _insert(self, household_id: int, conversation_id: int, new: NewFact, at: datetime) -> int:
        visibility = "private" if new.kind in ("health", "finance") and not new.visibility_stated else new.visibility
        fact_id = max(self.rows, default=0) + 1
        self.rows[fact_id] = Fact(fact_id, household_id, new.about_id, new.owner_id, visibility, new.kind, new.standing or new.kind == "diet",
                                  new.text,
                                  conversation_id, at, None, None)
        return fact_id

    def _forget(self, target: int) -> None:
        for row in [f for f in self.rows.values() if f.superseded_by == target]:
            self._forget(row.id)
        del self.rows[target]

    async def apply(self, household_id: int, conversation_id: int, ops: Sequence[Op], at: datetime,
                    written_through: int | None = None, written_from: int | None = None) -> tuple[int, ...]:
        targets = [op.target for op in ops if isinstance(op, (Update, Invalidate, Forget))]
        if any(t not in self.rows or self.rows[t].household_id != household_id or self.rows[t].valid_to for t in targets):
            raise ValueError("target is not a current fact of the household")
        inserted: list[int] = []
        for op in ops:
            if isinstance(op, (Add, Update)):
                inserted.append(self._insert(household_id, conversation_id, op.fact, at))
            if isinstance(op, Update):
                self.rows[op.target] = replace(self.rows[op.target], valid_to=at, superseded_by=inserted[-1])
            elif isinstance(op, Invalidate):
                self.rows[op.target] = replace(self.rows[op.target], valid_to=at)
            elif isinstance(op, Forget):
                self._forget(op.target)
        return tuple(inserted)

    async def similar(self, conversation: Conversation, limit: int) -> tuple[Fact, ...]:
        raise AssertionError("the recall eval never asks for the write job's candidates")

    async def held(self, household_id: int, person_id: int, fact_id: int | None = None) -> tuple[Held, ...]:
        raise AssertionError("the recall eval never runs the write job")

    async def forget(self, household_id: int, fact_id: int, by: int) -> int:
        raise AssertionError("the recall eval never runs the write job")

    async def embed_missing(self, limit: int) -> int:
        raise AssertionError("the recall eval never runs the write job")

    async def unwritten(self, idle_after_s: Mapping[ConversationKind, float], limit: int,
                        max_failures: int) -> tuple[Unwritten, ...]:
        raise AssertionError("the recall eval never runs the write job")

    async def write_failed(self, household_id: int, conversation_id: int, through: int) -> int:
        raise AssertionError("the recall eval never runs the write job")

    async def written_through(self, conversation_id: int) -> int | None:
        raise AssertionError("the recall eval never runs the write job")


class IgnoresVisibility(RuleMemory):
    def visible(self, fact: Fact, asker: Asker) -> bool:
        return True


class IgnoresHouseholds(RuleMemory):
    def in_household(self, fact: Fact, asker: Asker) -> bool:
        return True


class ReturnsClosedFacts(RuleMemory):
    def is_current(self, fact: Fact) -> bool:
        return True


class ForgetsNothing(RuleMemory):
    async def apply(self, household_id: int, conversation_id: int, ops: Sequence[Op], at: datetime,
                    written_through: int | None = None, written_from: int | None = None) -> tuple[int, ...]:
        return await super().apply(household_id, conversation_id, [o for o in ops if not isinstance(o, Forget)], at)


class PrivateWhenSpoken(RuleMemory):
    """Own private facts come back on any channel."""

    def visible(self, fact: Fact, asker: Asker) -> bool:
        return fact.visibility != "private" or fact.owner_id == asker.speaker_id


class VolunteersEveryDiscreetFact(RuleMemory):
    def volunteerable(self, fact: Fact, asker: Asker) -> bool:
        return True


class PrivateByAbout(RuleMemory):
    """Filters private facts by whom they are about instead of whose they are."""

    def visible(self, fact: Fact, asker: Asker) -> bool:
        if fact.visibility != "private":
            return super().visible(fact, asker)
        return asker.owner_only and fact.about_id == asker.speaker_id


class HidesDiscreetFromOwner(RuleMemory):
    def visible(self, fact: Fact, asker: Asker) -> bool:
        return super().visible(fact, asker) and not (fact.visibility == "discreet" and fact.owner_id == asker.speaker_id)


RECALL_MUTANTS: dict[str, Callable[[], Memory]] = {
    "ignores visibility": IgnoresVisibility,
    "ignores households": IgnoresHouseholds,
    "returns closed facts": ReturnsClosedFacts,
    "forgets nothing": ForgetsNothing,
    "own private on any channel": PrivateWhenSpoken,
    "volunteers every discreet fact": VolunteersEveryDiscreetFact,
    "private by about_id": PrivateByAbout,
    "hides discreet from its owner": HidesDiscreetFromOwner,
}

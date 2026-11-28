"""The pieces her commands touched, shown under her answer as runs and looks are."""

from collections.abc import Awaitable, Callable, Mapping, Sequence

from ..conversations.answers import answer_of
from ..conversations.model import Turn

Touched = Callable[[frozenset[int]], Awaitable[Mapping[int, tuple[int, ...]]]]


def under_answers(turns: Sequence[Turn], touched: Mapping[int, tuple[int, ...]]) -> dict[int, list[int]]:
    """The sorted piece ids to show under each turn of hers, keyed by its id: those `touched` by the person turn it
    answers (`Workshop.turn_pieces`, keyed by person turn id). A person turn with no answer yet, or none touched, is
    under none."""
    answers = answer_of(turns)
    return {answers[t]: list(ids) for t, ids in touched.items() if t in answers}

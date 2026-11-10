"""Which turn of hers answers which turn of a person's."""

from collections.abc import Sequence

from .model import Turn


def answer_of(turns: Sequence[Turn]) -> dict[int, int]:
    """Each person or household turn's id to the id of the turn that answers it: the last of hers that is not a held line and
    records (`Turn.answers`) answering it. A person turn with none, still owed its answer, has no entry. `turns` are
    one conversation's, oldest first."""
    answers: dict[int, int] = {}
    for turn in turns:
        if turn.answers is not None and not turn.follows:
            answers[turn.answers] = turn.id
    return answers

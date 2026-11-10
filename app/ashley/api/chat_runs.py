"""Which of her turns shows which code runs. A run is recorded against the person's turn that asked; the page shows it
under her final answer to that turn (the turn of hers recording that it answers it), not under a held line."""

from collections.abc import Sequence

from ..conversations.answers import answer_of
from ..conversations.model import Turn
from ..runs.model import Run
from .run_models import ChatRun, ChatRunFile


def wire(run: Run) -> ChatRun:
    out = run.output
    if out is None:
        return ChatRun(id=run.id, language=run.language, script=run.script, stdin=run.stdin, started_at=run.started_at,
                       finished_at=run.finished_at, result=None, exit_code=None, stdout="", stderr="", cut=False,
                       made=[], skipped=[])
    return ChatRun(id=run.id, language=run.language, script=run.script, stdin=run.stdin, started_at=run.started_at,
                   finished_at=run.finished_at, result=out.outcome, exit_code=out.exit_code, stdout=out.stdout,
                   stderr=out.stderr, cut=out.cut, made=[ChatRunFile(name=n, text=t) for n, t in out.files.items()],
                   skipped=list(out.skipped))


def under_answers(turns: Sequence[Turn], runs: Sequence[Run]) -> dict[int, list[ChatRun]]:
    """The runs to show under each turn of hers, keyed by its id, in the order they ran. A run whose person turn has
    no answer yet, or is not among `turns`, is under none."""
    answers = answer_of(turns)
    shown: dict[int, list[ChatRun]] = {}
    for run in sorted(runs, key=lambda r: r.id):
        under = None if run.turn_id is None else answers.get(run.turn_id)
        if under is not None:
            shown.setdefault(under, []).append(wire(run))
    return shown

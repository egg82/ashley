"""The code runs a reply's carried history brings (`respond` step 4): each carried answer of hers has the compact form
of the runs that its question asked for, placed by the rule the page uses (`conversations.answers.answer_of`)."""

import logging
from collections import defaultdict
from collections.abc import Sequence

from .. import logs, services
from ..conversations.answers import answer_of
from ..conversations.model import Turn
from ..runs.model import Run
from ..runs.runs import Runs, RunsUnavailable
from .limits import Limits

log = logging.getLogger("ashley.channels")


async def carried(household_id: int, turns: Sequence[Turn], said: Turn, limits: Limits) -> dict[int, str]:
    """Each carried turn of hers that answered a person turn with runs, keyed by id, to the compact form of those
    runs, one block each in the order they ran. `turns` are the carried ones oldest first and `said` the message
    being answered; one read of `Runs.of_turns` for the person turns among them, none when `limits.carried_runs` is 0
    or no person turn is carried. When the runs cannot be read the result is empty and `respond.runs_unavailable` is
    logged with the counts."""
    asked = tuple(t.id for t in turns if t.author == "person")
    if limits.carried_runs == 0 or not asked:
        return {}
    try:
        runs = await services.get(Runs).of_turns(household_id, asked, limits.carried_runs)
    except RunsUnavailable:
        logs.warning(log, "respond.runs_unavailable", conversation=said.conversation_id, person_turns=len(asked))
        return {}
    under = _under_answers(turns, said, runs)
    logs.info(log, "respond.runs", conversation=said.conversation_id, person_turns=len(asked), runs=len(runs),
              placed=sum(len(r) for r in under.values()))
    return {turn: "\n".join(block(r, limits) for r in found) for turn, found in under.items()}


def _under_answers(turns: Sequence[Turn], said: Turn, runs: Sequence[Run]) -> dict[int, list[Run]]:
    """The runs under each answer among `turns`. A conversation's turns are placed together, the message being
    answered ending its own, so a held line before it is not taken for the end of the exchange."""
    by_conversation: dict[int | None, list[Turn]] = defaultdict(list)
    for turn in (*turns, said):
        by_conversation[turn.conversation_id].append(turn)
    answers: dict[int, int] = {}
    for group in by_conversation.values():
        answers |= answer_of(group)
    under: dict[int, list[Run]] = defaultdict(list)
    for run in runs:
        answer = None if run.turn_id is None else answers.get(run.turn_id)
        if answer is not None:
            under[answer].append(run)
    return dict(under)


def block(run: Run, limits: Limits) -> str:
    """One run as the model reads it, between its own markers so it is not mistaken for her words: the language and
    how it ended, the script, what it printed to each stream, and the names of the files it made."""
    out = run.output
    ended = "no result was recorded" if out is None else _ended(out.outcome, out.exit_code)
    lines = [f"[code run: {run.language}, {ended}]", "script:", _head(run.script, limits.run_script_chars)]
    if out is not None:
        for name, text in (("stdout", out.stdout), ("stderr", out.stderr)):
            if text:
                lines += [f"{name}:", _tail(text, limits.run_output_chars)]
        if out.files:
            lines.append("files made: " + ", ".join(out.files))
    lines.append("[end code run]")
    return "\n".join(lines)


def _ended(outcome: str, exit_code: int | None) -> str:
    return f"ran, exit {exit_code}" if outcome == "ran" else outcome


def _head(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}\n... ({len(text) - limit} more characters)"


def _tail(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"... ({len(text) - limit} earlier characters)\n{text[len(text) - limit:]}"

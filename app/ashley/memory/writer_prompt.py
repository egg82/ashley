"""The memory writer's prompt: the rules in `writer.md` beside this module as the system prompt, and one person message
carrying the household's people, the known facts and the conversation. One message rather than one per turn, because
the conversation is the material being judged, not an exchange the model takes part in, and it usually ends on her
turn."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from importlib import resources
from zoneinfo import ZoneInfo

from ..conversations.model import Conversation, Turn
from ..inference.model import DEFAULT_VARIANT, Message, Prompt, SystemPrompt
from ..people.model import Household
from .model import Fact


def system() -> str:
    return resources.files("ashley.memory").joinpath("writer.md").read_text(encoding="utf-8").strip()


def prompt(conversation: Conversation, known: Sequence[Fact], household: Household, now: datetime) -> Prompt:
    """The prompt for one decision. Every person is named with their id, every known fact with its id, and every turn
    with its id and speaker: a person's name and id, `unknown speaker`, or `assistant`. The household's profile, when set,
    carries what the facts' wording needs, such as pronouns. `now` is shown in the household's local time, so a
    relative date can be made absolute."""
    names = {p.id: p.name for p in household.people}
    local = now.astimezone(ZoneInfo(household.timezone))
    parts = [
        f"Now: {local:%A %Y-%m-%d %H:%M}",
        "People:\n" + "\n".join(f"- {p.id}: {p.name}" for p in household.people),
        *(["Household:\n" + household.profile] if household.profile else []),
        "Known facts:\n" + ("\n".join(_fact(f, names) for f in known) or "(none)"),
        "Conversation:\n" + "\n".join(_turn(t, names) for t in conversation.turns),
    ]
    return Prompt(system={DEFAULT_VARIANT: SystemPrompt(system())}, messages=(Message("person", "\n\n".join(parts)),))


def _fact(fact: Fact, names: Mapping[int, str]) -> str:
    return (f"- id {fact.id}: about {_who(fact.about_id, names)}, owner {_who(fact.owner_id, names)}, "
            f"{fact.visibility}, {fact.kind}{', standing' if fact.standing else ''}: {fact.text}")


def _who(person_id: int | None, names: Mapping[int, str]) -> str:
    return "household" if person_id is None else f"{names.get(person_id, 'someone')} ({person_id})"


def _turn(turn: Turn, names: Mapping[int, str]) -> str:
    if turn.author == "ashley":
        return f"[turn {turn.id}] assistant: {turn.text}"
    if turn.speaker_id is None:
        return f"[turn {turn.id}] unknown speaker: {turn.text}"
    return f"[turn {turn.id}] {_who(turn.speaker_id, names)}: {turn.text}"

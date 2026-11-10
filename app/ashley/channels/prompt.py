"""The system prompt and the messages for one reply (`respond` steps 3 and 4). Every carried turn is marked with when it
was said, by the database's clock, in the household's local time (`stamp`), and one said on another thread than the
reply's with where (`placed.label`)."""

from collections.abc import Iterable, Mapping
from datetime import datetime
from zoneinfo import ZoneInfo

from ..conversations.model import Attachment, Kind, Place, Turn
from ..inference.model import Message, Role, SystemPrompt
from ..memory.model import Recalled
from ..people.model import Household
from ..persona import persona
from ..stamp import stamp
from ..tools.tools import Catalogue
from . import history_receipts, placed
from .speaker import Who


def system(kind: Kind, who: Who, place: str | None, catalogue: Catalogue | None,
           remembered: tuple[Recalled, ...] | None,
           standing: tuple[Recalled, ...] = (), phone: bool = False,
           page_open: bool | None = None, said_before: tuple[str, ...] = (),
           while_away: tuple[str, ...] = (), aloud: bool = False,
           overrides: Mapping[str, str] = persona.NO_OVERRIDES) -> Mapping[str, SystemPrompt]:
    """`persona.system` for this moment in the household's local time; `catalogue` None when tools are unreachable,
    `remembered` None when memory is, and `standing` is then empty; `phone`, whether `text` may go to the speaker's
    phone, and `page_open` whether they have a page open, told on a turn she was woken for; `said_before`, the relevant older turns as `said_before` renders them; `while_away`, the errand results to tell
    (`channels.owed.lines`); `aloud`, whether she may answer aloud (`channels.aloud.offered`); `overrides`, the
    household's persona overrides (`channels.taste.overrides`)."""
    context = persona.Context(
        now=datetime.now(ZoneInfo(who.household.timezone)),
        household=who.household,
        speaker=who.speaker,
        home=who.home,
        place=place,
        tool_instructions=catalogue.instructions if catalogue is not None else None,
        tools_reachable=catalogue is not None,
        tools_unreachable=catalogue.unreachable if catalogue is not None else (),
        tools_now=catalogue.now if catalogue is not None else None,
        remembered=remembered,
        standing=standing,
        phone=phone,
        page_open=page_open,
        aloud=aloud,
        said_before=said_before,
        while_away=while_away,
        overrides=overrides,
    )
    return persona.system(kind, context)


def messages(carried: Iterable[Turn], said: Turn, household: Household,
             runs: Mapping[int, str] | None = None, note: str | None = None,
             places: Mapping[int, Place] | None = None) -> tuple[Message, ...]:
    """The carried turns, those said elsewhere (`places`) first and then those said here, each group oldest first, then `said`, as model messages; a person turn whose speaker is known is prefixed
    `<name>: `, and each carried turn before that with when it was said, `(<stamp>) `, or `(<stamp>, <where>) ` when
    its id is in `places`. A turn of the household (a wake) opens `[From the <name> household, not words anyone said]`. A turn whose id is in `runs` ends with
    that text on a line of its own: the code runs it brought (`history_runs.carried`). A turn of hers with receipts
    ends with the line that says so (`history_receipts.line`), after those, and a person's agreeing turn with the line
    for what became of the calls (`history_receipts.agreed_line`). `note`, when set, ends `said` on a line of its own."""
    names = {p.id: p.name for p in household.people}
    zone = ZoneInfo(household.timezone)
    where = places or {}
    turns = tuple(carried)
    ordered = (*(t for t in turns if t.id in where), *(t for t in turns if t.id not in where))
    earlier = tuple(Message(_role(t), f"({_when(t, zone, where)}) {_said(t, names, household)}" + _with(runs, t) + history_receipts.after(t))
                    for t in ordered)
    return (*earlier, Message(_role(said), _said(said, names, household) + ('' if note is None else f'\n{note}')))


def said_before(relevant: Iterable[Turn], household: Household) -> tuple[str, ...]:
    """One line per relevant older turn, in the order given: `(<stamp>) <name>: <text>`, `You` for hers, the household's name for its own and
    `Someone` for a speaker not known; a turn of hers with receipts is followed by their line (`history_receipts.line`),
    and an agreeing turn by its outcome's (`history_receipts.agreed_line`)."""
    names = {p.id: p.name for p in household.people}
    zone = ZoneInfo(household.timezone)
    return tuple(f"({stamp(t.at, zone)}) {_who(t, names, household)}: {t.text}{history_receipts.after(t)}" for t in relevant)


def _when(turn: Turn, zone: ZoneInfo, places: Mapping[int, Place]) -> str:
    return stamp(turn.at, zone) + (f", {placed.label(places[turn.id])}" if turn.id in places else "")


def _role(turn: Turn) -> Role:
    return "ashley" if turn.author == "ashley" else "person"


def _said(turn: Turn, names: Mapping[int, str], household: Household) -> str:
    if turn.author == "household":
        return f"[From the {household.name} household, not words anyone said] {turn.text}"
    name = names.get(turn.speaker_id) if turn.author == "person" and turn.speaker_id is not None else None
    return (f"{name}: {turn.text}" if name is not None else turn.text) + _attached(turn.attachment)


def _attached(attachment: Attachment | None) -> str:
    """What the person pasted with a message, whole, marked as theirs to hand over and ended so it is never read as
    more of what they typed."""
    if attachment is None:
        return ""
    titled = "" if attachment.title is None else f' titled "{attachment.title}"'
    return (f"\n[They pasted this text with it{titled}, {len(attachment.text)} characters:]\n{attachment.text}\n"
            "[End of what they pasted.]")


def _with(runs: Mapping[int, str] | None, turn: Turn) -> str:
    return f"\n{runs[turn.id]}" if runs is not None and turn.id in runs else ""


def _who(turn: Turn, names: Mapping[int, str], household: Household) -> str:
    if turn.author == "ashley":
        return "You"
    if turn.author == "household":
        return household.name
    return names.get(turn.speaker_id, "Someone") if turn.speaker_id is not None else "Someone"

"""The facts section of the system prompt and the tools section after it, built from a `persona.Context`."""

from collections.abc import Iterable
from datetime import datetime

from ..memory.model import Recalled
from ..people.language import language_of
from ..people.model import Household, Person, UnitSystem
from ..stamp import stamp

UNREACHABLE = "You can't reach the house right now, so you can't read or change anything in it. Say so if asked."
SOURCE_UNREACHABLE = {
    "house": UNREACHABLE,
    "search": "You can't look things up right now. Say so if asked.",
    "everyday": UNREACHABLE,
}
MEMORY_UNREACHABLE = ("Your memory is out of reach right now, so nothing you learned in earlier conversations is here. "
                      "When asked about the household, its people or its pets, say your memory is out of reach rather "
                      "than that you don't know.")
STANDING = ("What is true of the people and home you serve, every time, whatever is said. Put the id of each one your "
            "reply relies on in `used_facts`. One marked (only if asked) you answer when asked about it directly, and "
            "never bring up yourself.")
PHONE = ("You can send `text` to {name}'s phone: set `to_phone` when the reply holds what doesn't work aloud (a link, "
         "a list, something long to keep). `text` may then be as long as that needs, and `spoken` says briefly that "
         "it's on their phone.")
PHONE_WOKEN = ("You were woken, not asked. {name} has no page open on any device, so nothing here reaches them until "
               "they look. A push reaches {name}'s phone: set `to_phone` to send `text` there.")
PHONE_WOKEN_OPEN = ("You were woken, not asked. {name} has a page open, so this reply is in front of them. A push also "
                    "reaches {name}'s phone: set `to_phone` to send `text` there too.")
ALOUD = ("{name} said this aloud, on a page that can play your voice: set `aloud` to have `spoken` played there. "
         "`text` is shown either way.")
ALOUD_UNKNOWN = ("This was said aloud, on a screen that can play your voice: set `aloud` to have `spoken` played "
                 "there. `text` is shown either way.")
REMEMBERED = ("What you learned in earlier conversations that may bear on this message. Put the id of each one your "
              "reply relies on in `used_facts`. One marked (only if asked) you answer when asked about it directly, "
              "and never bring up yourself.")
SAID_BEFORE = ("Said with you before, in earlier conversations or earlier in this one, that may bear on this message, "
               "each with when it was said.")
UNITS: dict[UnitSystem, str] = {
    "imperial": ("The household uses imperial units: temperatures in degrees Fahrenheit, distances in miles and feet, "
                 "weights in pounds and ounces, volumes in cups and fluid ounces."),
    "metric": ("The household uses metric units: temperatures in degrees Celsius, distances in kilometres and metres, "
               "weights in kilograms and grams, volumes in litres and millilitres."),
}
LANGUAGE = ("The household's language is {name}. Write `spoken` and `text` in {name}. When the person writes or speaks to "
            "you in another language, answer in theirs.")
THERMOSTAT_STEP: dict[UnitSystem, str] = {"imperial": "five", "metric": "three"}
STEP_TOKEN = "{thermostat_step}"
WHILE_AWAY = ("Asks you could not carry out when they were made, because a source was out of reach, and have done since. "
              "Each line is what you did, with when. Tell them so briefly, in your own words, once it fits their message; "
              "do not read the line out.")


def when(now: datetime) -> str:
    """`Sunday 25 October 2026, 7:34 pm`: the wall time `now` carries, with no conversion."""
    hour = now.hour % 12 or 12
    half = "am" if now.hour < 12 else "pm"
    return f"{now:%A} {now.day} {now:%B %Y}, {hour}:{now:%M} {half}"


def in_units(text: str, household: Household) -> str:
    """`text` with `STEP_TOKEN` (the size of a thermostat change she asks before making) written as a number of degrees
    in the household's unit system."""
    return text.replace(STEP_TOKEN, THERMOSTAT_STEP[household.unit_system])


def names(household: Household, ids: Iterable[int]) -> str:
    """The people with `ids`, in the household's order: `Ann`, `Ann and Bea`, `A, B and C`."""
    wanted = set(ids)
    found = [p.name for p in household.people if p.id in wanted]
    return found[0] if len(found) == 1 else ", ".join(found[:-1]) + " and " + found[-1]


def check(household: Household, speaker: Person | None, home: frozenset[int] | None, now: datetime) -> None:
    """ValueError for a naive `now`, or a speaker or anyone home who is not in `household`."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if speaker is not None and speaker not in household.people:
        raise ValueError("the speaker is not in the household")
    if home is not None and not home <= {p.id for p in household.people}:
        raise ValueError("someone home is not in the household")


def facts(
    now: datetime, household: Household, speaker: Person | None, home: frozenset[int] | None, place: str | None,
    phone: bool = False, page_open: bool | None = None, aloud: bool = False,
) -> str:
    lines = ["# Now", "", f"It is {when(now)}."]
    lines.append(
        "You don't know who is speaking." if speaker is None else f"{speaker.name} is speaking."
    )
    if phone and speaker is not None:
        lines.append(PHONE.format(name=speaker.name) if page_open is None else
                     (PHONE_WOKEN_OPEN if page_open else PHONE_WOKEN).format(name=speaker.name))
    if aloud:
        lines.append(ALOUD_UNKNOWN if speaker is None else ALOUD.format(name=speaker.name))
    if home is None:
        lines.append("You don't know who is home.")
    else:
        lines.append(f"Home now: {names(household, home)}." if home else "Nobody is home.")
    if place:
        lines.append(f"This device is in: {place}.")
    return "\n".join(lines)


def profile(household: Household) -> str:
    """`# This household`: the units it uses, the language it speaks when that is not English (`people.language`), then
    its profile when it has one."""
    text = household.profile.strip()
    language = language_of(household.locale)
    spoken = LANGUAGE.format(name=language.name) if language and language.code != "en" else ""
    return "# This household\n\n" + UNITS[household.unit_system] + ("\n\n" + spoken if spoken else "") + (
        "\n\n" + text if text else "")


def remembered(recalled: tuple[Recalled, ...] | None, now: datetime) -> str | None:
    """`# What you remember`: one `[id] (learned <stamp>) text` line per fact in the order given, the stamp in the zone of
    `now`, `(only if asked)` before the text of one she may not volunteer; the one unreachable line when `recalled` is None; nothing when it is empty."""
    if recalled is None:
        return "# What you remember\n\n" + MEMORY_UNREACHABLE
    if not recalled:
        return None
    return "# What you remember\n\n" + REMEMBERED + "\n\n" + "\n".join(_line(r, now) for r in recalled)


def said_before(lines: tuple[str, ...]) -> str | None:
    """`# Said before`: the lines in the order given; nothing when there are none."""
    if not lines:
        return None
    return "# Said before\n\n" + SAID_BEFORE + "\n\n" + "\n".join(lines)


def while_away(lines: tuple[str, ...]) -> str | None:
    """`# While they were away`: the lines in the order given; nothing when there are none."""
    if not lines:
        return None
    return "# While they were away\n\n" + WHILE_AWAY + "\n\n" + "\n".join(lines)


def tools_now(text: str | None) -> str | None:
    """The tool sources' state at this moment (`Catalogue.now`) as it is put in the `moment` layer; nothing when there is
    none."""
    return text.strip() if text and text.strip() else None


def standing(recalled: tuple[Recalled, ...], now: datetime) -> str | None:
    """`# What you always know`: one `[id] (learned <stamp>) text` line per fact in the order given, `(only if asked)` before one she may
    not volunteer; nothing when `recalled` is empty."""
    if not recalled:
        return None
    return "# What you always know\n\n" + STANDING + "\n\n" + "\n".join(_line(r, now) for r in recalled)


def _line(r: Recalled, now: datetime) -> str:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    learned = stamp(r.fact.valid_from, now.tzinfo)
    return f"[{r.fact.id}] (learned {learned}) {'' if r.may_volunteer else '(only if asked) '}{r.fact.text}"



def tools(tool_instructions: str | None, reachable: bool, unreachable: tuple[str, ...] = ()) -> str | None:
    """`# Tools`: the one unreachable line when no source answered; otherwise the sources' instructions, then one line
    per source that did not answer (`Catalogue.unreachable`; an unknown key says nothing); nothing when both are
    empty."""
    if not reachable:
        return "# Tools\n\n" + UNREACHABLE
    parts = [tool_instructions.strip()] if tool_instructions and tool_instructions.strip() else []
    lines = [SOURCE_UNREACHABLE[key] for key in unreachable if key in SOURCE_UNREACHABLE]
    if lines:
        parts.append(" ".join(lines))
    return "# Tools\n\n" + "\n\n".join(parts) if parts else None

"""The amount at the start of a recipe's ingredient line, and the line with that amount multiplied. An amount is a number
(whole, decimal, a fraction, a mixed number, a vulgar fraction, or a number word of `recipe.json`'s `words`), or a range
of two, then optionally a unit (`recipe.json`'s `units`, matched by alias as a whole word), then optionally a metric
equivalent in brackets, which is part of the amount and scales with it. A line that does not start with an amount, or
whose number is a size joined to a word by a hyphen, has none: it is shown as written and never scaled. This reads the
notation of a quantity only; the ingredient itself stays the page's words."""

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DATA = Path(__file__).with_name("recipe.json")
VULGAR = {"½": 1 / 2, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 1 / 4, "¾": 3 / 4, "⅕": 1 / 5, "⅖": 2 / 5, "⅗": 3 / 5, "⅘": 4 / 5,
          "⅙": 1 / 6, "⅚": 5 / 6, "⅛": 1 / 8, "⅜": 3 / 8, "⅝": 5 / 8, "⅞": 7 / 8}
FRACTIONS = ((0, ""), (1 / 8, "1/8"), (1 / 4, "1/4"), (1 / 3, "1/3"), (1 / 2, "1/2"), (2 / 3, "2/3"), (3 / 4, "3/4"),
             (1, ""))
GRAM_STEP_FROM = 100
GRAM_STEP = 5


@dataclass(frozen=True)
class Unit:
    key: str
    one: str
    many: str
    metric: bool


@dataclass(frozen=True)
class Amount:
    """`low` (and `high` for a range) in `unit` (None: a count), ending at character `end` of the line; `equivalent` is
    the bracketed metric amount after it and its unit, when there is one."""

    low: float
    high: float | None
    unit: Unit | None
    end: int
    equivalent: tuple[float, Unit] | None = None


def _load() -> tuple[dict[str, float], dict[str, Unit]]:
    raw: Any = json.loads(DATA.read_text())
    words = {str(k).lower(): float(v) for k, v in dict[str, Any](raw["words"]).items()}
    units: dict[str, Unit] = {}
    for key, entry in dict[str, Any](raw["units"]).items():
        unit = Unit(key, str(entry["one"]), str(entry["many"]), bool(entry.get("metric", False)))
        units.update({str(alias).lower(): unit for alias in entry["aliases"]})
    return words, units


WORDS, UNITS = _load()
_V = "".join(VULGAR)
_WORD = "|".join(re.escape(w) for w in sorted(WORDS, key=len, reverse=True))
_NUM = rf"(?:\d+(?:\s+and)?\s+\d+/\d+|\d+\s*[{_V}]|\d+/\d+|\d+(?:\.\d+)?|[{_V}]|(?:{_WORD})\b)"
_RANGE = re.compile(rf"\s*({_NUM})(?:\s*(?:-|–|—|\bto\b|\bor\b)\s*({_NUM}))?", re.IGNORECASE)
_ALIAS = "|".join(re.escape(a) for a in sorted(UNITS, key=len, reverse=True))
_UNIT = re.compile(rf"\s*({_ALIAS})(?![A-Za-z])\.?", re.IGNORECASE)
_EQUIVALENT = re.compile(rf"\s*\(\s*({_NUM})\s*({_ALIAS})(?![A-Za-z])\.?\s*\)", re.IGNORECASE)
_SIZE = re.compile(r"-[A-Za-z]")


def number_of(token: str) -> float:
    """The value of one number as `_NUM` matches it."""
    text = " ".join(token.lower().replace(" and ", " ").split())
    if text in WORDS:
        return WORDS[text]
    total = 0.0
    for part in re.findall(rf"\d+/\d+|\d+(?:\.\d+)?|[{_V}]", text):
        if part in VULGAR:
            total += VULGAR[part]
        elif "/" in part:
            top, bottom = part.split("/")
            total += int(top) / int(bottom) if int(bottom) else 0.0
        else:
            total += float(part)
    return total


def amount_of(line: str) -> Amount | None:
    """The amount `line` starts with; None when it starts with none."""
    found = _RANGE.match(line)
    if found is None or _SIZE.match(line, found.end()):
        return None
    low = number_of(found.group(1))
    high = None if found.group(2) is None else number_of(found.group(2))
    if low <= 0 or (high is not None and high <= low):
        return None
    end = found.end()
    unit_match = _UNIT.match(line, end)
    unit = None if unit_match is None else UNITS[unit_match.group(1).lower()]
    end = end if unit_match is None else unit_match.end()
    bracket = _EQUIVALENT.match(line, end)
    if bracket is not None and UNITS[bracket.group(2).lower()].metric:
        return Amount(low, high, unit, bracket.end(), (number_of(bracket.group(1)), UNITS[bracket.group(2).lower()]))
    return Amount(low, high, unit, end)


def number_text(value: float, unit: Unit | None) -> str:
    """`value` as a cook reads it, the one place amounts are rounded (the exact number stays in the data): grams as
    whole grams, to the nearest 5 from `GRAM_STEP_FROM` up; other metric units as whole numbers (one decimal under 10);
    anything else as a whole number and the nearest of `FRACTIONS`, never shown as nothing."""
    if unit is not None and unit.key == "gram":
        return str(_grams(value))
    if unit is not None and unit.metric:
        return str(round(value)) if value >= 10 else _trimmed(round(value, 1))
    whole = math.floor(value)
    part, name = min(FRACTIONS, key=lambda f: abs(value - whole - f[0]))
    whole += 1 if part == 1 else 0
    if not whole and not name:
        name = "1/8"
    if not name:
        return str(whole)
    return name if whole == 0 else f"{whole} {name}"


def scaled_line(line: str, amount: Amount, factor: float, metric_first: bool = False) -> str:
    """`line` with its amount multiplied by `factor` and written back in its unit, the rest of the line as it was.
    `metric_first`: a line that carries a metric equivalent leads with it and brackets the page's own amount."""
    low = amount.low * factor
    text = number_text(low, amount.unit)
    if amount.high is not None:
        text += "–" + number_text(amount.high * factor, amount.unit)
    if amount.unit is not None:
        many = (amount.high or amount.low) * factor > 1
        text += " " + (amount.unit.many if many else amount.unit.one)
    if amount.equivalent is not None:
        value, unit = amount.equivalent
        metric = f"{number_text(value * factor, unit)}{unit.one}"
        text = f"{metric} ({text})" if metric_first else f"{text} ({metric})"
    rest = line[amount.end:]
    return text + (rest if not rest or rest[0] in " ,;)" else " " + rest)


def _grams(value: float) -> int:
    if value < GRAM_STEP_FROM:
        return max(1, round(value))
    return math.floor(value / GRAM_STEP + 0.5) * GRAM_STEP


def _trimmed(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")

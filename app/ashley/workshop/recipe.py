"""A recipe piece's body (kind `recipe`, format `recipe`): a recipe as the page that published it gave it (its schema.org
Recipe data, read by `tools.recipe_ld`), with the headcount the bench wants it for. One JSON object of exactly
- `url`: the page's https URL (`embed.https_host`);
- `name`, `yield`: the recipe's name and how much it makes, as the page wrote them (`yield` may be empty);
- `ingredients`, `steps`: lists of the page's lines, at most `recipe.json`'s `max_ingredients` and `max_steps`, each
  at most `max_line_chars`;
- `prep_min`, `cook_min`, `total_min`: whole minutes, or null when the page gives none;
- `serves`: the headcount to scale to, 1 to `max_serves`, or null to show the recipe as written.
An empty body is a draft and passes.

Scaling is arithmetic here, never the model's: the page's yield count (the first number in `yield`, the low end of a
range) against `serves`, applied to every ingredient line whose amount `quantity` reads; the rest are shown as written
and marked so. Steps are never rewritten."""

import json
from dataclasses import dataclass
from typing import Any

from .embed import https_host
from .json_shape import object_of
from .quantity import DATA, amount_of, scaled_line

_TIMES = ("prep_min", "cook_min", "total_min")
_FIELDS = frozenset(("url", "name", "yield", "ingredients", "steps", "prep_min", "cook_min", "total_min", "serves"))
_LIMITS: Any = json.loads(DATA.read_text())
MAX_INGREDIENTS = int(_LIMITS["max_ingredients"])
MAX_STEPS = int(_LIMITS["max_steps"])
MAX_LINE = int(_LIMITS["max_line_chars"])
MAX_SERVES = int(_LIMITS["max_serves"])


@dataclass(frozen=True)
class Recipe:
    url: str
    name: str
    yield_text: str
    ingredients: tuple[str, ...]
    steps: tuple[str, ...]
    prep_min: int | None
    cook_min: int | None
    total_min: int | None
    serves: int | None = None


@dataclass(frozen=True)
class Line:
    """One ingredient line: `text` as the page wrote it and `shown` scaled (equal to `text` when it is not); `amount`
    and `amount_max` (a range's top) as the page gave them, in `unit` (None: a count, or no amount); `scaled` is whether
    `shown` was multiplied."""

    text: str
    shown: str
    amount: float | None
    amount_max: float | None
    unit: str | None
    scaled: bool


@dataclass(frozen=True)
class Scaled:
    """`recipe` for its `serves`: `makes` is the page's yield count (None when its yield names no number), `factor`
    what every amount was multiplied by (None when nothing was scaled: no `serves`, or no `makes`)."""

    recipe: Recipe
    makes: int | None
    factor: float | None
    lines: tuple[Line, ...]


def body_of(recipe: Recipe) -> str:
    """The body of a recipe piece holding `recipe`."""
    return json.dumps({"url": recipe.url, "name": recipe.name, "yield": recipe.yield_text,
                       "ingredients": list(recipe.ingredients), "steps": list(recipe.steps),
                       "prep_min": recipe.prep_min, "cook_min": recipe.cook_min, "total_min": recipe.total_min,
                       "serves": recipe.serves}, ensure_ascii=False)


def recipe_of(body: str) -> Recipe | None:
    """The recipe `body` holds; None when it is empty or not of the shape above."""
    try:
        loaded = object_of(json.loads(body))
    except ValueError:
        return None
    if loaded is None or frozenset(loaded) != _FIELDS:
        return None
    url, name, made = loaded["url"], loaded["name"], loaded["yield"]
    if not isinstance(url, str) or https_host(url) is None or not isinstance(name, str) or not isinstance(made, str):
        return None
    ingredients, steps = _lines(loaded["ingredients"], MAX_INGREDIENTS), _lines(loaded["steps"], MAX_STEPS)
    serves = loaded["serves"]
    if ingredients is None or steps is None or not all(_minutes(loaded[k]) for k in _TIMES):
        return None
    if serves is not None and (type(serves) is not int or not 1 <= serves <= MAX_SERVES):
        return None
    prep, cook, total = (_minute(loaded[k]) for k in _TIMES)
    return Recipe(url, name, made, ingredients, steps, prep, cook, total, serves)


def well_formed(body: str) -> bool:
    """Whether `body` is empty or a recipe of the shape above."""
    return not body.strip() or recipe_of(body) is not None


def makes_of(yield_text: str) -> int | None:
    """The count a yield names: its first number, the low end of a range; None when it names none."""
    for start in range(len(yield_text)):
        if start and yield_text[start - 1].isalnum():
            continue
        found = amount_of(yield_text[start:])
        if found is not None:
            return int(found.low) if found.low >= 1 else None
    return None


def scaled(recipe: Recipe, metric_first: bool = False) -> Scaled:
    """`recipe` with its ingredient amounts multiplied for its `serves`; `metric_first` as `quantity.scaled_line`."""
    makes = makes_of(recipe.yield_text)
    factor = None if recipe.serves is None or makes is None else recipe.serves / makes
    return Scaled(recipe, makes, factor, tuple(_line(text, factor, metric_first) for text in recipe.ingredients))


def text_of(recipe: Recipe, metric_first: bool = False) -> str:
    """The recipe as she reads it: name, source, how much it makes and for whom, times, the ingredients scaled (an
    unscaled line marked; `metric_first` as `quantity.scaled_line`), then the steps as the page wrote them."""
    view = scaled(recipe, metric_first)
    head = [recipe.name, f"Source: {recipe.url}", f"Makes (as the page says): {recipe.yield_text or 'not given'}"]
    if view.factor is not None:
        head.append(f"Scaled for {recipe.serves} from {view.makes}: every amount multiplied by "
                    f"{view.factor:.4g}; a line marked (as written) has no amount to scale")
    elif recipe.serves is not None:
        head.append(f"Not scaled for {recipe.serves}: the page's yield names no count")
    times = [f"{label} {m} min" for label, m in (("prep", recipe.prep_min), ("cook", recipe.cook_min),
                                                  ("total", recipe.total_min)) if m is not None]
    if times:
        head.append("Times: " + ", ".join(times))
    marked = view.factor is not None
    ingredients = [f"- {line.shown}" + (" (as written)" if marked and not line.scaled else "") for line in view.lines]
    steps = [f"{i}. {step}" for i, step in enumerate(recipe.steps, 1)]
    note = f" (as the page wrote them, for {view.makes})" if marked else ""
    return "\n".join([*head, "", "Ingredients:", *ingredients, "", f"Steps{note}:", *steps])


def _line(text: str, factor: float | None, metric_first: bool) -> Line:
    found = amount_of(text)
    if found is None:
        return Line(text, text, None, None, None, False)
    unit = None if found.unit is None else found.unit.key
    if factor is None:
        return Line(text, text, found.low, found.high, unit, False)
    return Line(text, scaled_line(text, found, factor, metric_first), found.low, found.high, unit, True)


def _lines(raw: object, most: int) -> tuple[str, ...] | None:
    loose: Any = raw
    if not isinstance(raw, list):
        return None
    lines = list[object](loose)
    if len(lines) > most or not all(isinstance(s, str) and len(s) <= MAX_LINE for s in lines):
        return None
    return tuple(str(s) for s in lines)


def _minute(raw: object) -> int | None:
    return raw if type(raw) is int else None


def _minutes(raw: object) -> bool:
    """Whether `raw` is whole minutes or null."""
    return raw is None or (type(raw) is int and raw >= 0)

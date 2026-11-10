"""The recipe a web page publishes as schema.org data: its `<script type="application/ld+json">` blocks, read as JSON,
and the first node whose `@type` is (or includes) `Recipe`, at the top level, in a list, or in a `@graph`. Its fields
become a `workshop.recipe.Recipe`: `name`, `recipeYield`, `recipeIngredient`, `recipeInstructions` (strings, HowToStep
and HowToSection, flattened in order), and `prepTime`, `cookTime`, `totalTime` as ISO 8601 durations. Text has its
markup and entities removed and its whitespace collapsed. The address is the one the page was read from, never the
data's own `url`. A page with no such node, or one without a name or ingredients, or over the piece's limits, has none."""

import html
import json
import re
from collections.abc import Iterator
from html.parser import HTMLParser
from typing import Any

from ..workshop import recipe
from ..workshop.json_shape import object_of

_DURATION = re.compile(r"P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?"
                       r"(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?", re.IGNORECASE)
_TAG = re.compile(r"<[^>]*>")


class _Blocks(HTMLParser):
    """Collects the text of each JSON-LD script element."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.blocks: list[str] = []
        self._open: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and any(k == "type" and (v or "").strip().lower() == "application/ld+json" for k, v in attrs):
            self._open = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._open is not None:
            self.blocks.append("".join(self._open))
            self._open = None

    def handle_data(self, data: str) -> None:
        if self._open is not None:
            self._open.append(data)


def blocks_of(page: str) -> list[str]:
    """The text of each JSON-LD block in the HTML `page`, in order."""
    parser = _Blocks()
    parser.feed(page)
    parser.close()
    return parser.blocks


def recipe_in(page: str, url: str) -> recipe.Recipe | None:
    """The recipe the HTML `page`, read from `url`, publishes; None when it publishes none this can use."""
    for block in blocks_of(page):
        try:
            data: object = json.loads(block, strict=False)
        except ValueError:
            continue
        for node in _nodes(data):
            found = _recipe_of(node, url)
            if found is not None:
                return found
    return None


def minutes_of(duration: object) -> int | None:
    """Whole minutes in an ISO 8601 duration; None when it is not one, or counts years or months."""
    if not isinstance(duration, str):
        return None
    found = _DURATION.fullmatch(duration.strip())
    if found is None or not any(found.groups()):
        return None
    years, months, weeks, days, hours, mins, secs = (float(g) if g else 0.0 for g in found.groups())
    if years or months:
        return None
    return round(weeks * 10080 + days * 1440 + hours * 60 + mins + secs / 60)


def clean(text: str) -> str:
    """`text` without markup or entities, its whitespace collapsed."""
    return " ".join(html.unescape(_TAG.sub(" ", html.unescape(text))).split())


def _nodes(data: object) -> Iterator[dict[str, Any]]:
    loose: Any = data
    if isinstance(data, list):
        for item in list[object](loose):
            yield from _nodes(item)
        return
    node = object_of(data)
    if node is None:
        return
    if "@graph" in node:
        yield from _nodes(node["@graph"])
    yield node


def _is_recipe(node: dict[str, Any]) -> bool:
    kind: object = node.get("@type")
    loose: Any = kind
    return kind == "Recipe" or (isinstance(kind, list) and "Recipe" in list[object](loose))


def _recipe_of(node: dict[str, Any], url: str) -> recipe.Recipe | None:
    if not _is_recipe(node):
        return None
    name = clean(node["name"]) if isinstance(node.get("name"), str) else ""
    ingredients = tuple(line for line in (clean(s) for s in _strings(node.get("recipeIngredient"))) if line)
    steps = tuple(line for line in (clean(s) for s in _steps(node.get("recipeInstructions"))) if line)
    if not name or not ingredients:
        return None
    found = recipe.Recipe(url, name, "; ".join(clean(s) for s in _strings(node.get("recipeYield"))), ingredients,
                          steps, minutes_of(node.get("prepTime")), minutes_of(node.get("cookTime")),
                          minutes_of(node.get("totalTime")))
    return found if recipe.recipe_of(recipe.body_of(found)) is not None else None


def _strings(raw: object) -> list[str]:
    """`raw` as a list of strings: a string or a number alone, or a list's strings and numbers."""
    loose: Any = raw
    items = list[object](loose) if isinstance(raw, list) else [raw]
    return [str(x) for x in items if isinstance(x, str) or (isinstance(x, (int, float)) and not isinstance(x, bool))]


def _steps(raw: object) -> list[str]:
    """The step texts of `recipeInstructions`, flattened in order."""
    loose: Any = raw
    if isinstance(raw, str):
        return clean_lines(raw)
    if isinstance(raw, list):
        return [step for item in list[object](loose) for step in _steps(item)]
    node = object_of(raw)
    if node is None:
        return []
    if "itemListElement" in node:
        return _steps(node["itemListElement"])
    text = node.get("text", node.get("name"))
    return [text] if isinstance(text, str) else []


def clean_lines(text: str) -> list[str]:
    """A block of instructions as its non-empty lines, markup taken as line breaks where it breaks lines."""
    broken = re.sub(r"<\s*(?:br|/p|/li)\s*/?>", "\n", text, flags=re.IGNORECASE)
    return [line for line in broken.split("\n") if line.strip()]

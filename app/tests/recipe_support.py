"""Helpers for the recipe tests: the JSON-LD blocks of four invented recipe pages (`recipe_captured/`, each file saying what
it imitates: two a plain fetch, two a headless browser's render), and a page around them.
The blocks are invented; the HTML around them (`page_of`) is written here."""

import json
from pathlib import Path
from typing import Any

CAPTURED = Path(__file__).parent / "recipe_captured"
PIE = "harvest_squash_pie"
MASH = "example_mashed_potatoes"
BRITT = "example_simple_mash"
CRANBERRY = "example_cranberry_relish"


def captured(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((CAPTURED / f"{name}.json").read_text(encoding="utf-8"))
    return loaded


def page_of(name: str, extra: str = "") -> str:
    """An HTML page holding the captured page's JSON-LD blocks, after an unrelated script and `extra`."""
    blocks = "".join(f'<script type="application/ld+json">{b}</script>' for b in captured(name)["blocks"])
    return (f"<html><head><title>{name}</title><script>var notData = 1;</script>{extra}{blocks}</head>"
            f"<body><p>Jump to recipe</p></body></html>")

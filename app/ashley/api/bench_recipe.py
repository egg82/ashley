"""A recipe piece as a screen shows it: its recipe scaled in code (`workshop.recipe.scaled`), so the card and her read
of the piece carry the same numbers."""

from ..workshop import recipe
from ..workshop.model import Piece
from ..workshop.rules import Kind
from .bench_recipe_models import PieceRecipe, RecipeLine


def recipe_of(piece: Piece, kind: Kind | None, metric: bool = False) -> PieceRecipe | None:
    """The recipe of a recipe piece, its amounts metric first when `metric`; None for any other kind and for an empty or malformed body."""
    found = recipe.recipe_of(piece.text.body) if kind is not None and kind.format == "recipe" else None
    if found is None:
        return None
    view = recipe.scaled(found, metric)
    return PieceRecipe(url=found.url, name=found.name, yield_text=found.yield_text, makes=view.makes,
                       serves=found.serves, factor=view.factor, prep_min=found.prep_min, cook_min=found.cook_min,
                       total_min=found.total_min, steps=list(found.steps),
                       ingredients=[RecipeLine(text=line.text, shown=line.shown, amount=line.amount,
                                               amount_max=line.amount_max, unit=line.unit, scaled=line.scaled)
                                    for line in view.lines])

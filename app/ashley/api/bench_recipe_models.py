"""Wire models for a recipe piece, understood and scaled for its headcount (`BenchPiece.recipe`)."""

from pydantic import BaseModel


class RecipeLine(BaseModel):
    """One ingredient line: `text` as the page wrote it, `shown` with its amount scaled (equal to `text` when it was
    not). `amount` and `amount_max` (a range's top) are the page's numbers in `unit` (a unit key of the server's units,
    null for a count or for a line with no amount); `scaled` says whether `shown` was multiplied."""

    text: str
    shown: str
    amount: float | None
    amount_max: float | None
    unit: str | None
    scaled: bool


class PieceRecipe(BaseModel):
    """A recipe piece's recipe: where it was published (`url`, https), its `name`, how much it makes as the page says
    (`yield_text`) and as a count (`makes`, null when that names no number), the headcount it is for (`serves`, null:
    as written) and what every amount was multiplied by (`factor`, null when nothing was scaled), the minutes it takes
    (each null when the page gives none), its ingredient lines and its steps as the page wrote them."""

    url: str
    name: str
    yield_text: str
    makes: int | None
    serves: int | None
    factor: float | None
    prep_min: int | None
    cook_min: int | None
    total_min: int | None
    ingredients: list[RecipeLine]
    steps: list[str]

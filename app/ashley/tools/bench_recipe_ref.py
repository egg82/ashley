"""Where a recipe piece's body comes from (`bench_reference.References`). She adds one by `result`, a page `read_page`
or `bench_read_piece` read this turn, and the server writes the body from the recipe that page publishes (`results.ReadPage.recipe`), never
from anything she typed; `serves`, a whole number, is the headcount it is scaled to in code. A page that publishes no
recipe is refused `no_recipe`. An edit may give `serves` alone, which rewrites only that field of the body as it is
now, or `result` (with `serves` optional) to put up a page read this turn in its place; a body she writes is refused,
since it would be a recipe and an address of her own."""

import dataclasses
from collections.abc import Iterable, Mapping

from ..workshop import recipe
from ..workshop.model import Piece
from .bench_args import BadArguments, piece_id_of, result_of
from .results import Results

NO_RECIPE = ("that page publishes no recipe data, so no recipe piece was added: put it up as a reader piece (its text) "
             "and take the amounts from its text, saying so")
UNREAD = ("a recipe piece holds the recipe of a page that was read this turn, and that result's page was not: read its "
          "site piece with bench_read_piece when one is up, or ask look_up for the page and to read it, in one question, "
          "and use the result number that gives")


class NoRecipe(Exception):
    """A recipe reference the bench tool refuses: `outcome` is its reason code, `reason` what she is told."""

    def __init__(self, outcome: str, reason: str) -> None:
        super().__init__(outcome)
        self.outcome = outcome
        self.reason = reason


def serves_of(args: Mapping[str, object]) -> int | None:
    """The optional `serves`, None when absent. Raises BadArguments when it is not a whole number in range."""
    if "serves" not in args:
        return None
    serves = args["serves"]
    if type(serves) is not int or not 1 <= serves <= recipe.MAX_SERVES:
        raise BadArguments(f"serves is a whole number of people, 1 to {recipe.MAX_SERVES}")
    return serves


def resolved(name: str, args: Mapping[str, object], results: Results, pieces: Iterable[Piece]) -> Mapping[str, object]:
    """`args` of `bench_add` or `bench_edit` on a recipe piece with `result` and `serves` replaced by the body they
    name. Raises BadArguments, NoRecipe."""
    if "start" in args:
        raise BadArguments("start is for a video")
    body = args.get("body")
    written = isinstance(body, str) and body.strip()
    serves = serves_of(args)
    kept = {k: v for k, v in args.items() if k not in ("result", "serves")}
    if "result" in args:
        if written:
            raise BadArguments("a recipe piece is put up by result, the number of a page that was read, not a body")
        return {**kept, "body": recipe.body_of(dataclasses.replace(_read(args, results), serves=serves))}
    if name == "bench_edit" and not written and serves is not None:
        return {**kept, "body": _reserved(args, pieces, serves)}
    raise BadArguments("a recipe piece is put up by result, the number of a page that was read, with serves; an edit "
                       "gives serves alone, or a result")


def _read(args: Mapping[str, object], results: Results) -> recipe.Recipe:
    number = result_of(args)
    url = results.url(number)
    if url is None:
        raise NoRecipe("unknown_result", "no search result with that number this turn: look it up again, and name a "
                                         "result by the number look_up's references give")
    page = results.page(number)
    if page is None:
        raise NoRecipe("unread_page", UNREAD)
    if page.recipe is None:
        raise NoRecipe("no_recipe", NO_RECIPE)
    return dataclasses.replace(page.recipe, url=url)


def _reserved(args: Mapping[str, object], pieces: Iterable[Piece], serves: int) -> str:
    """The body of the recipe piece `args` names with its `serves` changed."""
    piece = next((p for p in pieces if p.id == piece_id_of(args)), None)
    found = None if piece is None else recipe.recipe_of(piece.text.body)
    if found is None:
        raise BadArguments("that recipe piece holds no recipe yet: put one up by result")
    return recipe.body_of(dataclasses.replace(found, serves=serves))

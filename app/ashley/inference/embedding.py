"""What goes into and comes out of an embedding call, as values."""

from dataclasses import dataclass
from typing import Literal

EmbedTask = Literal["embed"]
"""What an embedding call is for, which picks its routes in `routes.json` beside the other tasks."""

EmbedRole = Literal["query", "passage"]
"""Which side of a search a text is: a `query` is what is asked, a `passage` is what is searched. Some models embed
the two differently, so a vector compares meaningfully only against one made in the other role by the same model."""


@dataclass(frozen=True)
class Embedded:
    """One unit-length vector per text, in the order of the texts, all `dimensions` long, made by `model` (the
    answering route's `Route.model`). Vectors from different models are not comparable."""

    vectors: tuple[tuple[float, ...], ...]
    model: str

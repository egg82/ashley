"""Printables' records, neutral of its GraphQL shapes. A model is named by its `id` (digits); a design file by its `id`
within a model."""

from dataclasses import dataclass
from typing import Literal

Reason = Literal["unreachable", "not_found", "needs_login", "too_large", "unexpected"]
"""Why a call failed: `unreachable`, no answer, a timeout or a server error; `not_found`, no such model; `needs_login`,
the site would not hand the file to a visitor who has not logged in; `too_large`, the file is over the limit given;
`unexpected`, what answered is not Printables' API, or a download link pointed outside Printables' file hosts."""


@dataclass(frozen=True)
class ModelFile:
    """One file of a model: the `id` that names it for a download, its `name` as the author gave it, its `size` in
    bytes."""

    id: str
    name: str
    size: int


@dataclass(frozen=True)
class Model:
    """A model as a search gives it. `rating` is the average out of 5, None when nobody rated it."""

    id: str
    name: str
    url: str
    author: str
    summary: str
    likes: int
    downloads: int
    makes: int
    rating: float | None
    files: tuple[ModelFile, ...]


@dataclass(frozen=True)
class Detail:
    """A model with what its own page holds. `description` is the HTML the author wrote."""

    model: Model
    description: str
    license: str
    category: str
    published: str

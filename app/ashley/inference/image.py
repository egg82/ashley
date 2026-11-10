"""What goes into and comes out of an image call, as values."""

from dataclasses import dataclass
from typing import Literal

ImageTask = Literal["image"]
"""What an image call is for, which picks its routes in `routes.json` beside the text tasks."""

Aspect = Literal["square", "wide", "tall"]
"""The shape asked for: 1:1, 3:2 across, 2:3 high. Each provider maps it to its own size or ratio."""


@dataclass(frozen=True)
class Imaged:
    """A picture a provider drew: its encoded `data` (`media_type`, as the provider declared it, not yet judged) and the
    route that drew it (`Route.provider`, `Route.model`)."""

    data: bytes
    media_type: str
    provider: str
    model: str

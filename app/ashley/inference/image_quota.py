"""How many pictures a household may have drawn in a window: the limit is data (`image.json` beside this module) and the
count is read from the spend ledger, so every pod and both sites count the same calls. A call counts when it was made
for a conversation of the household and the provider drew a picture or declined (`ok`, `refused`); a call that failed
cost nothing. A conversation deleted takes its calls out of the count."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib import resources

from ..db.database import Database
from .image_http import obj
from .inference import ImageCapped


@dataclass(frozen=True)
class ImageLimit:
    """At most `max_per_household` pictures in any `window_s` seconds."""

    max_per_household: int
    window_s: int


def load() -> ImageLimit:
    """The limit shipped in `image.json`. Raises ValueError as `parse`."""
    return parse(json.loads(resources.files("ashley.inference").joinpath("image.json").read_text()))


def parse(data: object) -> ImageLimit:
    """An ImageLimit from JSON already parsed. Raises ValueError unless it is an object of exactly `max_per_household`
    and `window_s`, each a whole number above 0."""
    values = obj(data)
    if values is None or set(values) != {"max_per_household", "window_s"}:
        raise ValueError("image limit is an object of max_per_household and window_s")
    for key, value in values.items():
        if type(value) is not int or value <= 0:
            raise ValueError(f"{key}: expected a whole number above 0")
    return ImageLimit(int(str(values["max_per_household"])), int(str(values["window_s"])))


class ImageCap:
    def __init__(self, count: Callable[[int, int], Awaitable[int]], limit: ImageLimit) -> None:
        """`count(household_id, window_s)` is how many pictures the household has had drawn in the window: `drawn`,
        over a database."""
        self._count = count
        self._limit = limit

    async def check(self, household_id: int) -> None:
        """Raises ImageCapped when the household's count has reached the limit. Raises what the count raises."""
        if await self._count(household_id, self._limit.window_s) >= self._limit.max_per_household:
            raise ImageCapped(self._limit.max_per_household, self._limit.window_s)


async def drawn(database: Database, household_id: int, window_s: int) -> int:
    """The pictures of `household_id` the ledger counts in the last `window_s` seconds, by the database's clock."""
    async with database.connection() as conn:
        row = await (await conn.execute(
            "SELECT count(*) FROM inference_calls c JOIN conversations v ON v.id = c.conversation_id "
            "WHERE c.task = 'image' AND c.outcome IN ('ok', 'refused') AND v.household_id = %s "
            "AND c.at > now() - make_interval(secs => %s)", (household_id, window_s))).fetchone()
    return int(row[0]) if row else 0

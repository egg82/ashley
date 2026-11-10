"""Keeping a picture she was given in a bench turn, whatever made it (`bench_look`, `bench_frames`): its bytes in the
object store under the looks' own prefix and its row in `Looks`, which also counts a turn's pictures against
`max_looks_per_turn`."""

import hashlib

from .. import services
from ..files.store import ObjectStore
from ..inference.model import Image
from ..looks.keys import key_of
from ..looks.looks import Looks, NewLook


async def over_limit(household_id: int, turn_id: int, call_id: str, limit: int) -> str | None:
    """What she is told when person turn `turn_id` has already kept `limit` pictures for calls other than `call_id`,
    else None. Raises `looks.looks.LooksUnavailable`."""
    taken = await services.get(Looks).taken(household_id, turn_id, call_id)
    if taken < limit:
        return None
    return f"you have taken {taken} looks for this message, the most it allows; say what you saw"


async def keep(household_id: int, said: tuple[int, int], call_id: str, bench_id: int, piece_id: int | None,
               picture: Image) -> None:
    """Store `picture` and record it against `said` (conversation id, person turn id) and tool call `call_id`. Raises
    `files.store.StoreUnavailable` and `looks.looks.LooksUnavailable`."""
    sha = hashlib.sha256(picture.data).hexdigest()
    await services.get(ObjectStore).put(key_of(household_id, sha), picture.data)
    await services.get(Looks).keep(NewLook(household_id, *said, call_id, bench_id, piece_id, sha, picture.media_type,
                                           len(picture.data)))

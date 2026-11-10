"""The text of a text-like file piece, for her to read: the bytes from the object store, decoded. A binary file has none."""

from .. import services
from ..files.config import FilesConfig
from ..files.intake import key_of
from ..files.store import ObjectStore
from ..workshop import stored_file
from ..workshop.model import Piece


def is_text(media_type: str, config: FilesConfig) -> bool:
    return media_type in config.text_types or media_type.startswith("text/")


async def text_of(household_id: int, piece: Piece, config: FilesConfig) -> str | None:
    """The text of file piece `piece` when its bytes are text, None when they are not or the piece names no file.
    Raises `files.store.StoreUnavailable`; a file no store holds reads as an empty text."""
    file = stored_file.file_of(piece.text.body)
    if file is None or not is_text(file.media_type, config):
        return None
    data = await services.get(ObjectStore).get(key_of(household_id, file.sha256))
    return "" if data is None else data.decode("utf-8", errors="replace")

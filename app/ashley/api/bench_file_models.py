"""Wire model for an image or file piece's bytes (`BenchPiece.file`) and the link that reaches them."""

import time

from pydantic import BaseModel

from ..files import config as files_config
from ..files import links
from ..workshop import stored_file
from ..workshop.rules import Kind

CONFIG = files_config.load()


class PieceFile(BaseModel):
    """An `image` or `file` piece's bytes, understood: the file's `name`, `size_bytes` and `media_type`. `url` is a
    link to the bytes (same site, no session needed) that stops working at `expires_at` (Unix seconds), so a page that
    stays open reads the bench again before then; null when this process mints no links. `image` says the page may
    show it in place; any file may be saved from `url`."""

    name: str
    size_bytes: int
    media_type: str
    image: bool
    url: str | None
    expires_at: int | None


def piece_file(household_id: int, body: str, kind: Kind | None, key: bytes, now: float | None = None) -> PieceFile | None:
    """The file a large piece's `body` names, None for any other kind or a body that names none. The link is minted
    under `key` (empty: no link) to end with the current half-`link_ttl_s` window after `now`."""
    if kind is None or kind.family != "large":
        return None
    file = stored_file.file_of(body)
    if file is None:
        return None
    image = CONFIG.is_image(file.media_type)
    if not key:
        return PieceFile(name=file.name, size_bytes=file.size, media_type=file.media_type, image=image, url=None,
                         expires_at=None)
    ends = links.window_end(time.time() if now is None else now, CONFIG.link_ttl_s)
    link = links.mint(key, links.Grant(household_id, file.sha256, file.media_type, image or CONFIG.plays(file.media_type),
                                       ends))
    return PieceFile(name=file.name, size_bytes=file.size, media_type=file.media_type, image=image, url=link.url,
                     expires_at=link.expires_at)

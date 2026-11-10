"""Wire model for a video piece's body understood by the server (`BenchPiece.video`)."""

from pydantic import BaseModel

from ..workshop.embed import Provider


class PieceVideo(BaseModel):
    """A video piece's video: its `provider` (`youtube`, `vimeo`, or `file` for a direct media file), the `url` as
    written, the `embed_url` to frame (a `file`'s is its own url, to play in a video element) with the start already in
    it, and `start`, where it begins in whole seconds. A site's url is its body."""

    provider: Provider
    url: str
    embed_url: str
    start: int

"""What a bench read offers her from the tidy pass: the findings that still stand, as a short list to verify against the
pieces. A finding whose quote is no longer in its piece (she fixed it, or the person did) is cleared here, and a
dismissed one is kept only while its quote stands, so the same passage is not pointed at again."""

from collections.abc import Iterable

from ..workshop.model import Piece
from .config import TidyConfig
from .tidy import Tidy, TidyUnavailable


async def to_check(tidy: Tidy, bench_id: int, pieces: Iterable[Piece], config: TidyConfig) -> list[dict[str, object]]:
    """The bench's open findings whose quote is still in its piece, oldest first, at most `config.shown`, as
    `{id, piece_id, kind, quote, other_piece_id, why}`; the findings whose quote is gone are deleted. Empty when the
    record cannot be reached."""
    bodies = {p.id: p.text.body for p in pieces}
    try:
        held = await tidy.findings(bench_id)
        gone = tuple(f.id for f in held if f.quote not in bodies.get(f.piece_id, ""))
        await tidy.clear(bench_id, gone)
    except TidyUnavailable:
        return []
    standing = [f for f in held if f.id not in gone and not f.dismissed]
    return [{"id": f.id, "piece_id": f.piece_id, "kind": f.kind, "quote": f.quote, "other_piece_id": f.by_piece_id,
             "why": f.why} for f in standing[:config.shown]]

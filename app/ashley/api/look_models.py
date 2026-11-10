"""Wire model for a look shown under her reply (`api.chat_looks`)."""

from pydantic import BaseModel

from .workshop_models import BenchDetail, WorkshopKinds


class ChatLook(BaseModel):
    """A picture she was given of a bench for a message, as the page shows it under her answer: of piece `piece_id`
    of bench `bench_id`, or of the whole bench when `piece_id` is null. `url` is a link to the picture (same site, no
    session needed) that stops working at `expires_at` (Unix seconds), so a page that stays open reads the
    conversation again before then; null when this process mints no links."""

    id: int
    bench_id: int
    piece_id: int | None
    media_type: str
    url: str | None
    expires_at: int | None


class LookPage(BaseModel):
    """What the page a browser pod photographs reads (`GET /api/look/{token}`): the bench as its owner sees it, or one
    piece of it, and the kinds the page needs to draw a piece, which the session-only kinds route would not give it."""

    view: BenchDetail
    rules: WorkshopKinds

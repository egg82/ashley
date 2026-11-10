"""Wire model for a site piece's address as the server measured it (`BenchPiece.site`)."""

from pydantic import BaseModel

from ..workshop.workshop import SiteFrame


class PieceSite(BaseModel):
    """A site piece's address, measured. `frameable` is true when the site lets a page frame it, false when it refused
    (an `X-Frame-Options` of DENY or SAMEORIGIN, a `frame-ancestors` that leaves this page out, or a non-2xx answer), and
    null when it is not known (not measured yet, or the site did not answer): a screen shows it as it would a site that
    may or may not frame. `title` is the page's own, empty when none was read."""

    frameable: bool | None
    title: str


def site_of(frame: SiteFrame | None) -> PieceSite:
    return PieceSite(frameable=None, title="") if frame is None else PieceSite(frameable=frame.frameable, title=frame.title)

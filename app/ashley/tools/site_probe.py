"""Asking a site whether it lets a page frame it: the page reader's request (`PageReader.reply`, behind its
request-forgery checks) judged by `frame_policy`."""

from .. import services
from ..workshop.frame_probe import FrameProbe
from ..workshop.workshop import SiteFrame
from . import frame_policy, look_up_config, page_fetch, page_reader


class PageFrameProbe(FrameProbe):
    async def measure(self, url: str, origin: str) -> SiteFrame:
        limits = page_reader.limits_of(look_up_config.load())
        try:
            reply = await services.get(page_reader.PageReader).reply(url, limits)
        except (page_fetch.Refused, page_fetch.NoPage):
            return SiteFrame(None)
        return SiteFrame(frame_policy.frameable(reply, origin), reply.title)


def register() -> None:
    """Make the frame probe, the answer to `services.get(FrameProbe)`, asking through the registered `PageReader`."""
    services.register(FrameProbe, PageFrameProbe())

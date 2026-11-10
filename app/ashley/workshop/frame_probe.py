"""The FrameProbe service (`ashley.services`): whether the site at an address lets a page frame it. The implementation
asks the site over the network, which the workshop never does itself (`tools.site_probe`)."""

from abc import abstractmethod

from ..services import Service
from .workshop import SiteFrame


class FrameProbe(Service):
    @abstractmethod
    async def measure(self, url: str, origin: str) -> SiteFrame:
        """What the site at `url` says about being framed by a page at `origin` (where this page is reached, possibly
        empty). `frameable` is None when the site could not be asked. Never raises."""

    @classmethod
    def null(cls) -> "FrameProbe":
        return NullFrameProbe()


class NullFrameProbe(FrameProbe):
    async def measure(self, url: str, origin: str) -> SiteFrame:
        return SiteFrame(None)

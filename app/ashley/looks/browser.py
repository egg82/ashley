"""The PageBrowser service (`ashley.services`): read one public web page in a headless browser somewhere with no state,
for a page the plain fetch was refused (`tools.page_reader`). `kubernetes_browser.KubernetesBrowser` runs the look
pod's browser in a pod of its own that may reach public HTTPS and nothing private; the Null Object reads nothing. The
browser is Chromium as it comes: it says it is headless, and a site that refuses it is refused, never worked around.
The page's address is not logged."""

from abc import abstractmethod
from dataclasses import dataclass

from ..services import Service


class BrowseUnavailable(Exception):
    """The page could not be read in a browser: none is wired, the pod could not run, or the page did not load in time.
    `args[0]` is a short reason."""


@dataclass(frozen=True)
class Browsed:
    """What the browser was given for the page: the main response's `status` and content `kind` (the type without
    parameters, empty when it sent none), the document as the browser holds it once loaded (`text`, HTML for a page),
    the `bytes` of it brought back, and whether it was `cut` at the limit."""

    status: int
    kind: str
    text: str
    bytes: int
    cut: bool


class PageBrowser(Service):
    @classmethod
    def null(cls) -> "PageBrowser":
        return NullPageBrowser()

    @abstractmethod
    def reads(self) -> bool:
        """Whether it can read a page at all."""

    @abstractmethod
    async def read(self, url: str) -> Browsed:
        """Open `url` (an https address the caller has checked is public) in a fresh browser and return what it was
        given, whatever the status. Raises BrowseUnavailable. Leaves nothing behind."""


class NullPageBrowser(PageBrowser):
    def reads(self) -> bool:
        return False

    async def read(self, url: str) -> Browsed:
        raise BrowseUnavailable("not_wired")

"""The Printables service (`ashley.services`): 3D models people published at printables.com, as neutral records. It
reads only what a visitor who is not logged in can: a search, a model's details and a design file. Callers import this module and `model`; the GraphQL adapter lives beside them. A call logs `printables.call` with
the call, the outcome, the count and the duration; never a query, a name or a link."""

import re
from abc import abstractmethod
from urllib.parse import urlsplit

from ..services import Service
from .model import Detail, Model, Reason

_MODEL_PATH = re.compile(r"^/(?:[a-z]{2}(?:-[a-z]{2})?/)?model/(\d{1,12})(?:-[^/]*)?/?$")
SITE_HOSTS = frozenset({"www.printables.com", "printables.com"})


class PrintablesFailed(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


def model_id_of(url: str) -> str | None:
    """The model a Printables model page's URL names, by its parsed host and path; None for any other URL."""
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in SITE_HOSTS:
        return None
    found = _MODEL_PATH.match(parts.path)
    return found.group(1) if found else None


class Printables(Service):
    @classmethod
    def null(cls) -> "Printables":
        return NullPrintables()

    @abstractmethod
    async def search(self, query: str) -> list[Model]:
        """The models matching `query`, best first, up to the configured count. Raises PrintablesFailed."""

    @abstractmethod
    async def detail(self, model_id: str) -> Detail:
        """The model `model_id` with its description. Raises PrintablesFailed (`not_found` for no such model)."""

    @abstractmethod
    async def download(self, model_id: str, file_id: str, max_bytes: int) -> bytes:
        """The bytes of file `file_id` of model `model_id`, from one of Printables' file hosts. Raises PrintablesFailed
        (`needs_login` when the site will not hand the file over, `too_large` over `max_bytes`)."""


class NullPrintables(Printables):
    async def search(self, query: str) -> list[Model]:
        raise PrintablesFailed("unreachable")

    async def detail(self, model_id: str) -> Detail:
        raise PrintablesFailed("unreachable")

    async def download(self, model_id: str, file_id: str, max_bytes: int) -> bytes:
        raise PrintablesFailed("unreachable")

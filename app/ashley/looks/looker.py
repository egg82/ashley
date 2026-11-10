"""The Looker service (`ashley.services`), the Strategy a screenshot goes through: open a page in a headless browser
somewhere with no state and bring back what it drew. `kubernetes.KubernetesLooker` runs a browser in a pod of its own;
the Null Object renders nothing, so only an image piece can be looked at. The page's path carries a token that names whose bench it is and
is a credential for a short while: it is never logged."""

from abc import abstractmethod
from dataclasses import dataclass

from ..services import Service


class LookUnavailable(Exception):
    """The page could not be drawn: the browser could not be started, the page never said it was ready, or it drew
    nothing readable. Nothing was kept."""


@dataclass(frozen=True)
class Shot:
    """What a browser drew: a JPEG of the page."""

    data: bytes


@dataclass(frozen=True)
class Target:
    """What to draw: bench `bench_id` of `person_id` in `household_id` as that person sees it, narrowed to piece
    `piece_id` when it is not None, and a model drawn from the side `view` (one of `ashley.looks.views.VIEWS`) when that
    is not None, its four-view sheet otherwise."""

    household_id: int
    person_id: int
    bench_id: int
    piece_id: int | None
    view: str | None = None


class Looker(Service):
    @classmethod
    def null(cls) -> "Looker":
        return NullLooker()

    @abstractmethod
    def renders(self) -> bool:
        """Whether it can draw a page at all."""

    @abstractmethod
    async def look(self, name: str, target: Target) -> Shot:
        """Open the app's page for `target` (the looker knows where the app is and mints the link) in a fresh browser
        and return a screenshot of it once the page says it is drawn. `name` is unique
        per look and safe as a Kubernetes name (`look-<...>`). Raises LookUnavailable. Leaves nothing behind: whatever
        drew the page is gone when this returns or raises."""


class NullLooker(Looker):
    def renders(self) -> bool:
        return False

    async def look(self, name: str, target: Target) -> Shot:
        raise LookUnavailable("Looker is not wired")

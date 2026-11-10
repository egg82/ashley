"""The Tidy service (`ashley.services`): what a cheap model pointed at in a bench's text pieces, kept for her to verify.
A finding names a passage by its exact quote and says how it is wrong; it is a pointer, never a verdict, and she is the
one who acts on it (an ordinary edit) or dismisses it. The record is in Postgres, so any pod of either site offers the
same findings and a pass survives neither pod nor needs to. Callers import only this module; `postgres.PostgresTidy`
implements it."""

from abc import abstractmethod
from dataclasses import dataclass
from typing import Literal, get_args

from ..services import Service

Kind = Literal["superseded", "contradicts", "debris", "duplicate"]
"""How a passage is wrong: `superseded` (a newer passage replaces it), `contradicts` (another passage conflicts with it),
`debris` (what editing left behind: a repeated heading, an empty item, a cut-off sentence) or `duplicate` (it repeats
another passage)."""

KINDS: tuple[Kind, ...] = get_args(Kind)


class TidyUnavailable(Exception):
    """The record could not be read or written."""


@dataclass(frozen=True)
class NewFinding:
    """A passage a pass pointed at: `quote`, the exact text span in piece `piece_id`; `by_piece_id`, the piece holding
    the passage it was judged against (None when that is in the same piece or there is none); `why`, a short reason."""

    piece_id: int
    kind: Kind
    quote: str
    by_piece_id: int | None
    why: str


@dataclass(frozen=True)
class Finding:
    """A kept finding. `dismissed` ones stay, unseen, so the same passage is not pointed at again while it stands."""

    id: int
    piece_id: int
    kind: Kind
    quote: str
    by_piece_id: int | None
    why: str
    dismissed: bool


class Tidy(Service):
    @classmethod
    def null(cls) -> "Tidy":
        return NullTidy()

    @abstractmethod
    async def checked(self, bench_id: int) -> dict[int, int]:
        """The piece versions the bench's last finished pass saw, by piece id; empty when none finished. Raises
        TidyUnavailable."""

    @abstractmethod
    async def begin(self, household_id: int, bench_id: int, lock_s: int) -> bool:
        """Take the bench for a pass; False when another pass took it less than `lock_s` seconds ago. A pass that never
        finishes releases itself by age. Raises TidyUnavailable."""

    @abstractmethod
    async def finish(self, household_id: int, bench_id: int, versions: dict[int, int], found: tuple[NewFinding, ...],
                     keep_s: int) -> None:
        """Record the pass as done over `versions` and release the bench: its open findings are replaced by `found`
        (a passage already dismissed is not added again), and findings older than `keep_s` seconds are deleted, dismissed
        ones too. All in one transaction. Raises TidyUnavailable."""

    @abstractmethod
    async def release(self, bench_id: int) -> None:
        """Release the bench without recording the pass, so the next turn's pass runs over the same changes. Raises
        TidyUnavailable."""

    @abstractmethod
    async def findings(self, bench_id: int) -> tuple[Finding, ...]:
        """Every kept finding of the bench, dismissed included, oldest first. Raises TidyUnavailable."""

    @abstractmethod
    async def dismiss(self, bench_id: int, finding_id: int) -> bool:
        """Mark the bench's finding dismissed; False when the bench has no such finding. Raises TidyUnavailable."""

    @abstractmethod
    async def clear(self, bench_id: int, finding_ids: tuple[int, ...]) -> None:
        """Delete the bench's findings with these ids. Raises TidyUnavailable."""


class NullTidy(Tidy):
    """Keeps nothing and says so: what an unwired process sees."""

    async def checked(self, bench_id: int) -> dict[int, int]:
        raise TidyUnavailable("Tidy is not wired")

    async def begin(self, household_id: int, bench_id: int, lock_s: int) -> bool:
        raise TidyUnavailable("Tidy is not wired")

    async def finish(self, household_id: int, bench_id: int, versions: dict[int, int], found: tuple[NewFinding, ...],
                     keep_s: int) -> None:
        raise TidyUnavailable("Tidy is not wired")

    async def release(self, bench_id: int) -> None:
        raise TidyUnavailable("Tidy is not wired")

    async def findings(self, bench_id: int) -> tuple[Finding, ...]:
        return ()

    async def dismiss(self, bench_id: int, finding_id: int) -> bool:
        return False

    async def clear(self, bench_id: int, finding_ids: tuple[int, ...]) -> None:
        pass

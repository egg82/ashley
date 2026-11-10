"""A code host's records, neutral between forges: a project is named by its `path` (`group/name`, `owner/repo`), which
every call takes back."""

from dataclasses import dataclass, field
from typing import Literal

Forge = Literal["gitlab", "github"]
Reason = Literal["refused", "not_found", "unreachable", "too_large", "unexpected"]
"""Why a call failed: `refused`, the host turned the token away (401, 403); `not_found`, no such project, path or ref
(or one the token cannot see); `unreachable`, no answer, a timeout, or a server error; `too_large`, an archive over the
cap; `unexpected`, what answered is not the host's API."""


@dataclass(frozen=True)
class Access:
    """Who a call is made as: the forge, the host's address and the person's token. The token is left out of `repr`, so
    a log line or a traceback that prints this cannot carry it. `connection` is the stored connection the token came
    from, whose `checked_at` an answered call moves; None for a token not yet stored."""

    forge: Forge
    base_url: str
    token: str = field(repr=False)
    connection: int | None = None


@dataclass(frozen=True)
class Project:
    id: int
    path: str
    description: str
    default_branch: str | None


@dataclass(frozen=True)
class Entry:
    path: str
    kind: Literal["file", "dir"]


@dataclass(frozen=True)
class Page[T]:
    """What one answer holds, and whether more was left out."""

    items: tuple[T, ...]
    more: bool


@dataclass(frozen=True)
class Fetched:
    """Bytes fetched, cut at the cap asked for: `more` says the file went on."""

    data: bytes
    more: bool

"""What may name a project, a path or a ref in a request URL. A value that fails is refused before any URL is built, so
the final request path stays under the forge's API prefix: no dot segment (`.`, `..`, or either percent-encoded), no
empty segment, no separator hidden inside a segment. A refusal logs `codehost.refused` with the forge, the kind and the
reason, never the value."""

import logging
import re
from typing import Literal
from urllib.parse import quote, unquote

from .. import logs
from .host import CodeHostFailed
from .model import Forge

log = logging.getLogger("ashley.codehost")
Kind = Literal["project", "path", "ref"]
_GITLAB = re.compile(r"^\w[\w.-]*$", re.ASCII)
_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")
_REPO = re.compile(r"^[\w.-]+$", re.ASCII)


def _decoded(segment: str) -> str:
    for _ in range(4):
        again = unquote(segment)
        if again == segment:
            break
        segment = again
    return segment


def _segment_reason(segment: str) -> str | None:
    plain = _decoded(segment)
    if plain == "":
        return "empty_segment"
    if plain in (".", ".."):
        return "dot_segment"
    if "/" in plain or "\\" in plain or "\x00" in plain:
        return "separator"
    return None


def _free_reason(value: str) -> str | None:
    if value == "":
        return None
    return next((r for r in map(_segment_reason, value.split("/")) if r), None)


def _project_reason(forge: Forge, value: str) -> str | None:
    parts = value.split("/")
    reason = next((r for r in map(_segment_reason, parts) if r), None)
    if reason:
        return reason
    if forge == "gitlab":
        numeric = len(parts) == 1 and value.isascii() and value.isdigit()
        return None if numeric or (len(parts) >= 2 and all(_GITLAB.match(p) for p in parts)) else "shape"
    return None if len(parts) == 2 and _OWNER.match(parts[0]) and _REPO.match(parts[1]) else "shape"


def reason(forge: Forge, kind: Kind, value: str) -> str | None:
    """Why `value` may not name a `kind` on `forge` (`empty_segment`, `dot_segment`, `separator`, `shape`), or None.
    A project is a GitLab numeric id or `group/.../name`, a GitHub `owner/repo`; an empty path or ref means the root or
    the default branch."""
    return _project_reason(forge, value) if kind == "project" else _free_reason(value)


def ensure(forge: Forge, kind: Kind, value: str) -> None:
    """Raises CodeHostFailed (`not_found`) when `reason` finds one."""
    why = reason(forge, kind, value)
    if why is not None:
        logs.info(log, "codehost.refused", forge=forge, kind=kind, reason=why)
        raise CodeHostFailed("not_found")


def encoded(value: str) -> str:
    """The segments of an `ensure`d path or ref, each percent-encoded, joined by `/`."""
    return "/".join(quote(p, safe="") for p in value.split("/"))

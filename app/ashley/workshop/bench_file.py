"""Putting a file on a bench: the bytes judged and kept (`ashley.files.intake`), then an ordinary Add of an `image` or
`file` piece naming them, so the piece is as visible and as undoable as any other. The only way a large piece is made:
the routes and her tools refuse an Add of one with a body they wrote (`needs_bytes`)."""

from .. import services
from ..files import config as files_config
from ..files.config import FilesConfig
from ..files.intake import Stored, take
from . import stored_file
from .commands import Add
from .model import By, Owner, Size, Text
from .rules import Rules
from .workshop import Applied, Workshop

SIZES: dict[str, Size] = {"image": "medium", "clip": "medium", "audio": "medium", "file": "small"}
CONFIG = files_config.load()


def needs_bytes(rules: Rules, kind: str) -> bool:
    """Whether pieces of `kind` can only be made from bytes: a large kind."""
    found = rules.kinds.get(kind)
    return found is not None and found.family == "large"


async def add_file(owner: Owner, bench_id: int, by: By, data: bytes, raw_name: str, declared: str, rules: Rules,
                   config: FilesConfig | None = None) -> tuple[Stored, Applied]:
    """Keep `data` and add it to bench `bench_id` last, as the kind of piece its bytes are (`image`, `clip`, `audio`,
    else `file`, by `FilesConfig.piece_kind`), titled by its name. Raises `files.intake.Refused` and `files.store.StoreUnavailable` (nothing was added),
    and the Workshop's own errors (the bytes stay stored: they are keyed by their hash, and a retry reuses them). The
    Add can still be refused (`full`); the `Applied` says."""
    config = config or CONFIG
    stored = await take(owner.household_id, data, raw_name, declared, config)
    kind = config.piece_kind(stored.media_type)
    body = stored_file.body_of(stored_file.StoredFile(stored.sha256, stored.size, stored.media_type, stored.name))
    title = stored.name[:rules.title_max_chars].strip() or "file"
    return stored, await services.get(Workshop).apply(owner, bench_id, Add(by, kind, Text(title, body), SIZES[kind]))

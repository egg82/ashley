"""Mail's tunables, data in `mail.json` beside this module: how long before an OAuth access token expires a pod
refreshes it (`refresh_margin_s`); how long a call to a mail service may take (`timeout_s`); the most headers one search
answers (`search_max`) and labels one listing holds (`labels_max`); the longest snippet kept (`snippet_chars`); the
longest body text kept from a message (`body_chars`); the most bytes read of one message's answer (`message_bytes`);
the longest message id an adapter takes (`message_id_chars`); and for changes, the longest draft body (`max_body_chars`,
held against `max_argument_chars` in `ashley/tools/outside.json` by `tests/test_mail_change_limits.py`, since a held send
past that limit is refused), the most recipients of one draft (`max_recipients`, to and cc together) and the most
messages one label call names (`max_change_ids`). Proton Bridge's keeping: how often its keeper
reports (`heartbeat_s`), how long a keeper may go unanswered, or a pod unheard, before it counts as stopped
(`fence_s`), the extra wait a new holder adds past that (`fence_margin_s`), the pause before a pod that ended is
replaced (`restart_s`), how often the singleton looks (`tick_s`) and the size of the pod's cache volume (`cache_mib`)."""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("mail.json")


@dataclass(frozen=True)
class MailConfig:
    refresh_margin_s: int
    timeout_s: float
    search_max: int
    labels_max: int
    snippet_chars: int
    body_chars: int
    message_bytes: int
    message_id_chars: int
    max_body_chars: int
    max_recipients: int
    max_change_ids: int
    heartbeat_s: int
    fence_s: int
    fence_margin_s: int
    restart_s: int
    tick_s: int
    cache_mib: int


def load() -> MailConfig:
    """The tunables shipped in `mail.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> MailConfig:
    """A MailConfig from parsed JSON. Raises ValueError for a missing or unknown key or a value that is not a positive
    integer (`timeout_s`: a positive number)."""
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError("mail config is an object")
    raw = dict[object, object](loose)
    names = [f.name for f in fields(MailConfig)]
    missing = [n for n in names if n not in raw]
    unknown = sorted(str(k) for k in raw if k not in names)
    if missing or unknown:
        raise ValueError(f"mail config keys: missing {missing}, unknown {unknown}")
    counts = {n: _count(n, raw[n]) for n in names if n != "timeout_s"}
    timeout = raw["timeout_s"]
    if isinstance(timeout, bool) or not isinstance(timeout, int | float) or not timeout > 0:
        raise ValueError("timeout_s: expected a positive number")
    return MailConfig(timeout_s=float(timeout), **counts)


def _count(name: str, value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name}: expected a positive integer")
    return value

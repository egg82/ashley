"""The deposit sense's tunables, data in `deposits.json` beside this module: `poll_s` between polls; `lookback_days`, how
far before the day it last read it reads again, so a deposit Sure dates earlier than it posted is still seen (below
the wakes' keeping, `keep_s`, so a prune never lets a fired deposit fire again); `per_page` and `max_pages`, how many
transactions it reads from Sure per request and at most per poll; `proposal_ttl_s`, how long a proposed rule waits for the
person's answer; `timeout_s` is Sure's own, in `money.json`.
The rest bound the conditions she composes (`ashley.criteria.predicates`): `judged_days`, the payer history a fire she
judges carries; `default_days`, `default_min_seen` and `default_tolerance_days`, what a history predicate gets for a
parameter she leaves out; `max_days`, `max_tolerance_days`, `max_clauses` and `max_predicates`, the most she may set."""

import json
from dataclasses import astuple, dataclass
from pathlib import Path

FILE = Path(__file__).with_name("deposits.json")
CRITERIA = ("judged_days", "default_days", "max_days", "default_min_seen", "default_tolerance_days",
            "max_tolerance_days", "max_clauses", "max_predicates")


@dataclass(frozen=True)
class Criteria:
    judged_days: int
    default_days: int
    max_days: int
    default_min_seen: int
    default_tolerance_days: int
    max_tolerance_days: int
    max_clauses: int
    max_predicates: int


@dataclass(frozen=True)
class DepositConfig:
    poll_s: float
    lookback_days: int
    per_page: int
    max_pages: int
    proposal_ttl_s: float
    criteria: Criteria

    @property
    def judged_days(self) -> int:
        return self.criteria.judged_days


def load() -> DepositConfig:
    """The tunables shipped in `deposits.json`. Raises ValueError when one is missing, unknown or not positive."""
    raw = json.loads(FILE.read_text())
    if set(raw) != {"poll_s", "lookback_days", "per_page", "max_pages", "proposal_ttl_s", *CRITERIA}:
        raise ValueError("deposits.json has exactly poll_s, lookback_days, per_page, max_pages and the criteria ones")
    criteria = Criteria(*(int(raw[k]) for k in CRITERIA))
    made = DepositConfig(float(raw["poll_s"]), int(raw["lookback_days"]), int(raw["per_page"]), int(raw["max_pages"]),
                         float(raw["proposal_ttl_s"]), criteria)
    if min(made.poll_s, made.lookback_days, made.per_page, made.max_pages, made.proposal_ttl_s, *astuple(criteria)) <= 0 \
            or made.per_page > 100 or criteria.default_days > criteria.max_days \
            or criteria.default_tolerance_days > criteria.max_tolerance_days:
        raise ValueError("deposit tunables are positive, per_page is at most Sure's 100, and defaults are within limits")
    return made


CONFIG = load()

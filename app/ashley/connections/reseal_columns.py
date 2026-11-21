"""Every column that holds a sealed value, and how to rebuild the binding each one is sealed with from its own row.
`ashley.connections.reseal` walks this list; `tests/test_reseal.py` fails for a `bytea` column that is neither here nor
listed there as holding something else, so a newly sealed column cannot be missed."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .sealing import KEEPER_BOUND, KEYCHAIN_BOUND, VAULT_BOUND, bound_to


@dataclass(frozen=True)
class SealedColumn:
    """`column` of `table`, whose rows are told apart by `key` (a `key_type` value). `extra` names the other columns the
    binding is made from, in the order `bound` takes them as one row. `shown` is whether `key` may be logged."""

    table: str
    column: str
    key: str
    key_type: str
    extra: tuple[str, ...]
    bound: Callable[[tuple[Any, ...]], bytes]
    shown: bool = True

    @property
    def name(self) -> str:
        return f"{self.table}.{self.column}"


def _connection(row: tuple[Any, ...]) -> bytes:
    return bound_to(row[0], row[1], row[2])


def _pending(row: tuple[Any, ...]) -> bytes:
    return f"connect:{row[0]}:{row[1]}".encode()


def _fixed(bound: bytes) -> Callable[[tuple[Any, ...]], bytes]:
    return lambda row: bound


_CONNECTION = ("household_id", "kind", "person_id")

SEALED: tuple[SealedColumn, ...] = (
    SealedColumn("connections", "secret", "id", "bigint", _CONNECTION, _connection),
    SealedColumn("connections", "access_token", "id", "bigint", _CONNECTION, _connection),
    SealedColumn("deployment_secrets", "sealed", "name", "text", ("name",),
                 lambda row: f"deployment:{row[0]}".encode()),
    SealedColumn("connect_pending", "verifier", "state_sha256", "bytea", ("household_id", "person_id"), _pending,
                 shown=False),
    SealedColumn("proton_bridge", "vault", "id", "bigint", (), _fixed(VAULT_BOUND)),
    SealedColumn("proton_bridge", "keychain", "id", "bigint", (), _fixed(KEYCHAIN_BOUND)),
    SealedColumn("proton_bridge", "keeper_access", "id", "bigint", (), _fixed(KEEPER_BOUND)),
)

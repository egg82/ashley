"""A model provider reached with a key a person pastes in the connections room (Type Object): its connection kind, the
route names it serves, and what one key turns on. The four are declared in `ashley.inference.kinds`; `KeyedProviders`
builds them from the keys in force (`ashley.inference.provider_keys`)."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from ..connections.kinds import ConnectionKind
from .balance import BalanceSource
from .provider import Wired


@dataclass(frozen=True)
class Built:
    """What one key turns on: `wired`, each under its own route name, `balances`, the providers among them that report a
    remaining quota, by name (empty for most), and `close`, which releases their HTTP clients. A build never makes a
    request until it is called, and its key is in no field `repr` shows."""

    wired: tuple[Wired, ...]
    balances: Mapping[str, BalanceSource]
    close: Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class AddressedProvider:
    """A provider reached at an address a person gives and no key (Wyoming speech-to-text): `kind` is its connection
    kind, a `deployment` kind of the `inference` port whose `name` is also the slot its address is read under; `names`
    are the route names every build of it carries; `build` turns an address into its `Built`, raising ValueError for
    an address it cannot reach."""

    kind: ConnectionKind
    names: frozenset[str]
    build: Callable[[str], Built]

    def __post_init__(self) -> None:
        if not self.kind.deployment or "inference" not in self.kind.ports or self.kind.name not in self.names:
            raise ValueError("an addressed provider's kind is a deployment kind of the inference port, named as a route")


@dataclass(frozen=True)
class KeyedProvider:
    """`kind` is the connection kind a person adds the key as (its `name` is the provider's: `anthropic`, `openai`,
    `gemini`, `elevenlabs`; it is a `deployment` kind implementing the `inference` port). `names` are the route names
    every build of it carries (`openai` and `openai_image` for OpenAI's key), none shared with another provider.
    `build` turns one key into its `Built`; it never raises for a key's content, since a key is checked by the kind's
    `check` when a person adds it and by the provider's answer on each call."""

    kind: ConnectionKind
    names: frozenset[str]
    build: Callable[[str], Built]

    def __post_init__(self) -> None:
        if self.kind.fixed_address is None or not self.kind.deployment or "inference" not in self.kind.ports:
            raise ValueError("a keyed provider's kind is a deployment kind of the inference port at a fixed address")

    @property
    def address(self) -> str:
        """The provider's one API address, its kind's `fixed_address`."""
        return self.kind.fixed_address or ""

"""The service locator (Nystrom, Game Programming Patterns, "Service Locator"). A system many places call has one
interface, a subclass of `Service`; callers ask `get(Interface)` and never import what implements it. The composition
root (`ashley.wiring`) registers each implementation at startup. Unregistered, `get` answers the interface's Null
Object, which does nothing and says so in the log once, so a tool or test runs unwired and a missed registration is
seen rather than a crash. Only for systems: a leaf helper stays a plain import."""

import logging
from abc import ABC, abstractmethod
from typing import TypeVar

from . import logs

log = logging.getLogger("ashley.services")


class Service(ABC):
    """An interface reached through the locator."""

    @classmethod
    @abstractmethod
    def null(cls) -> "Service":
        """The Null Object: what `get` answers when nothing is registered."""


S = TypeVar("S", bound=Service)
_live: dict[type[Service], Service] = {}
_nulls: dict[type[Service], Service] = {}


def register(interface: type[S], provider: S) -> None:
    """Make `provider` the answer to `get(interface)`. Refuses anything that is not that interface."""
    if not isinstance(provider, interface):
        raise TypeError(f"{type(provider).__name__} is not a {interface.__name__}")
    _live[interface] = provider


def unregister(interface: type[Service]) -> None:
    """Back to the Null Object."""
    _live.pop(interface, None)


def clear() -> None:
    """Every interface back to its Null Object."""
    _live.clear()


def get(interface: type[S]) -> S:
    """The registered provider of `interface`, or its Null Object."""
    found = _live.get(interface)
    if isinstance(found, interface):
        return found
    null = _nulls.get(interface)
    if isinstance(null, interface):
        return null
    made = interface.null()
    if not isinstance(made, interface):
        raise TypeError(f"{interface.__name__}.null() returned a {type(made).__name__}")
    _nulls[interface] = made
    logs.warning(log, "service.null", service=interface.__name__)
    return made

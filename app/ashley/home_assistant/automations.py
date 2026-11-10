"""A house's automations: list them, read and write one's config by its id, delete one, turn one on or off. Each
household's are reached through its Home (`homes.automations_of`); `rest_automations.RestAutomations` implements them
over Home Assistant's REST API. A config is HA's own automation config as a JSON object; it is the household's
data and is never logged."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any


class AutomationsUnavailable(Exception):
    """Home Assistant could not be reached, or answered in a way this does not read. What was asked may or may not
    have happened; the message names the step, never a config or the token."""


class AutomationRejected(Exception):
    """Home Assistant refused the config it was given (its own validation); nothing was written. `message` is HA's own
    reason, which names fields of the config and nothing else."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Automation:
    """One automation of the house: `automation_id` its config's id (None for one written in YAML without one, which
    cannot be read or written here), its `entity_id` (`automation.<x>`), `alias` (its friendly name), whether it is
    `enabled` (on), and when it last fired, None for never."""

    automation_id: str | None
    entity_id: str
    alias: str
    enabled: bool
    last_triggered: datetime | None


class Automations(ABC):
    @abstractmethod
    def offered(self) -> bool:
        """Whether there is a house at all; her automation tools are offered only then."""

    async def has_service(self, name: str) -> bool | None:
        """Whether the house has the Home Assistant service `name` (`domain.service`); None when that cannot be told
        (no house, or it is out of reach)."""
        return None

    @abstractmethod
    async def listed(self) -> list[Automation]:
        """Every automation of the house, by entity id. Raises AutomationsUnavailable."""

    @abstractmethod
    async def config(self, automation_id: str) -> dict[str, Any] | None:
        """The config of the automation with that id, as HA holds it (its `id` included); None when there is none.
        Raises AutomationsUnavailable."""

    @abstractmethod
    async def write(self, automation_id: str, config: Mapping[str, Any]) -> str | None:
        """Write `config` as the automation with that id, creating it or replacing the one there; HA reloads it.
        Returns its entity id once HA shows it, None when it had not appeared in time. Raises AutomationRejected
        (nothing written); AutomationsUnavailable."""

    @abstractmethod
    async def delete(self, automation_id: str) -> bool:
        """Delete the automation with that id; False when there was none. Raises AutomationsUnavailable."""

    @abstractmethod
    async def set_enabled(self, entity_id: str, enabled: bool) -> None:
        """Turn automation `entity_id` on or off. Raises AutomationsUnavailable."""


class NullAutomations(Automations):
    """No house: nothing is offered, and every call raises AutomationsUnavailable."""

    def offered(self) -> bool:
        return False

    async def listed(self) -> list[Automation]:
        raise AutomationsUnavailable("no house")

    async def config(self, automation_id: str) -> dict[str, Any] | None:
        raise AutomationsUnavailable("no house")

    async def write(self, automation_id: str, config: Mapping[str, Any]) -> str | None:
        raise AutomationsUnavailable("no house")

    async def delete(self, automation_id: str) -> bool:
        raise AutomationsUnavailable("no house")

    async def set_enabled(self, entity_id: str, enabled: bool) -> None:
        raise AutomationsUnavailable("no house")

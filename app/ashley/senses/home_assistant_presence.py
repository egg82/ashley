"""Presence from Home Assistant: each person's `home_assistant` account (`People.accounts`) names their HA `person`
entity (`person.alana`), read through `/api/states/<entity>`; state `home` is home, any other state is away. One
unreadable entity makes the whole answer unknown, since a set missing someone would read as their being away."""

import asyncio
import logging
import time
from urllib.parse import quote

import httpx2
from pydantic import BaseModel, ValidationError

from .. import logs
from ..home_assistant.client import HomeAssistant
from ..people.model import Account
from ..people.people import People, PeopleUnavailable
from .presence import Presence

log = logging.getLogger("ashley.senses")
SYSTEM = "home_assistant"


class _State(BaseModel):
    state: str


class _Unreadable(Exception):
    """One entity could not be read; `reason` is a code, never a URL or a body."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class HomeAssistantPresence(Presence):
    def __init__(self, home_assistant: HomeAssistant, people: People, timeout_s: float = 5.0) -> None:
        self._http = home_assistant.http
        self._people = people
        self._timeout_s = timeout_s

    async def home(self, household_id: int) -> frozenset[int] | None:
        started = time.monotonic()
        try:
            accounts = await self._people.accounts(household_id, SYSTEM)
            if not accounts:
                return self._unknown("unmapped", started)
            states = await asyncio.gather(*(self._state(a) for a in accounts), return_exceptions=True)
        except PeopleUnavailable:
            return self._unknown("people_unavailable", started)
        for state in states:
            if isinstance(state, _Unreadable):
                return self._unknown(state.reason, started)
            if isinstance(state, BaseException):
                raise state
        at_home = frozenset(a.person_id for a, state in zip(accounts, states, strict=True) if state == "home")
        logs.info(log, "presence.read", home=len(at_home), duration_ms=int((time.monotonic() - started) * 1000))
        return at_home

    async def _state(self, account: Account) -> str:
        try:
            response = await self._http.get(f"/api/states/{quote(account.external_id, safe='')}",
                                            timeout=self._timeout_s)
        except httpx2.TimeoutException as e:
            raise _Unreadable("timeout") from e
        except httpx2.HTTPError as e:
            raise _Unreadable("unreachable") from e
        if response.status_code != 200:
            raise _Unreadable(f"http_{response.status_code}")
        try:
            return _State.model_validate_json(response.content).state
        except ValidationError as e:
            raise _Unreadable("malformed") from e

    def _unknown(self, reason: str, started: float) -> None:
        logs.warning(log, "presence.unknown", reason=reason, duration_ms=int((time.monotonic() - started) * 1000))

"""Devices in Postgres, table `devices`. `add`, `revoke`, `set_satellite` and `set_discord_server` are the admin CLI's
(`python -m ashley.channels.devices`); the app only signs devices in and lists satellites and Discord servers."""

import hashlib
import logging
import secrets
from typing import Any, get_args

import psycopg

from .. import logs
from ..conversations.model import Kind
from ..db.database import Database, DatabaseUnavailable
from . import device_rate
from .device_rate import Rate
from .devices import Devices, DevicesUnavailable
from .model import Audience, Capability, Device, DiscordServer, Listed, Medium, Satellite

log = logging.getLogger("ashley.channels.devices")

_AUDIENCES: dict[str, Audience] = {a: a for a in get_args(Audience)}
_MEDIA: dict[str, Medium] = {m: m for m in get_args(Medium)}
_KINDS: dict[str, Kind] = {k: k for k in get_args(Kind)}
_CAPABILITIES: dict[str, Capability] = {c: c for c in get_args(Capability)}


class UnknownHousehold(Exception):
    """`add` named a household that does not exist."""


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


class PostgresDevices(Devices):
    def __init__(self, database: Database, rate: Rate | None = None) -> None:
        self._database = database
        self._rate = device_rate.load() if rate is None else rate

    async def by_token(self, token: str) -> Device | None:
        if not token:
            return None
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT id, household_id, name, place, audience, medium, kind, remembers FROM devices "
                    "WHERE token_sha256 = %s AND revoked_at IS NULL",
                    (token_hash(token),),
                )
                row = await cur.fetchone()
        except (DatabaseUnavailable, psycopg.OperationalError) as e:
            raise DevicesUnavailable("database unreachable") from e
        return None if row is None else _device(row)

    async def allow(self, device_id: int) -> bool:
        window = self._rate.window_seconds
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "WITH w AS (SELECT to_timestamp(floor(extract(epoch FROM now()) / %(s)s) * %(s)s) AS start), "
                    "old AS (DELETE FROM device_requests WHERE device_id = %(d)s "
                    "AND window_start < (SELECT start FROM w)) "
                    "INSERT INTO device_requests (device_id, window_start, requests) "
                    "SELECT %(d)s, start, 1 FROM w "
                    "ON CONFLICT (device_id, window_start) DO UPDATE SET requests = device_requests.requests + 1 "
                    "RETURNING requests",
                    {"s": window, "d": device_id},
                )
                row = await cur.fetchone()
        except (DatabaseUnavailable, psycopg.OperationalError) as e:
            raise DevicesUnavailable("database unreachable") from e
        assert row is not None
        return row[0] <= self._rate.max_requests

    async def satellites(self) -> list[Satellite]:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT id, household_id, name, place, audience, medium, kind, remembers, esphome_host, "
                    "room_speaker "
                    "FROM devices WHERE esphome_host IS NOT NULL AND revoked_at IS NULL ORDER BY id"
                )
                rows = await cur.fetchall()
        except (DatabaseUnavailable, psycopg.OperationalError) as e:
            raise DevicesUnavailable("database unreachable") from e
        return [Satellite(_device(row), row[8], row[9]) for row in rows]

    async def discord_servers(self) -> list[DiscordServer]:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT id, household_id, name, place, audience, medium, kind, remembers, discord_guild_id, "
                    "discord_home_channel_id "
                    "FROM devices WHERE discord_guild_id IS NOT NULL AND revoked_at IS NULL ORDER BY id"
                )
                rows = await cur.fetchall()
        except (DatabaseUnavailable, psycopg.OperationalError) as e:
            raise DevicesUnavailable("database unreachable") from e
        return [DiscordServer(_device(row), row[8], row[9]) for row in rows]

    async def of_household(self, household_id: int) -> list[Listed]:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT id, household_id, name, place, audience, medium, kind, remembers, "
                    "esphome_host IS NOT NULL, discord_guild_id IS NOT NULL, house, capabilities "
                    "FROM devices WHERE household_id = %s AND revoked_at IS NULL ORDER BY id",
                    (household_id,),
                )
                rows = await cur.fetchall()
        except (DatabaseUnavailable, psycopg.OperationalError) as e:
            raise DevicesUnavailable("database unreachable") from e
        return [Listed(_device(row), "satellite" if row[8] else "discord_server" if row[9] else "house" if row[10]
                       else "other",
                       _capabilities(row[11])) for row in rows]

    async def set_satellite(self, device_id: int, host: str, room_speaker: str | None) -> bool:
        """Make the unrevoked device `device_id` a satellite at `host`, its reply played on `room_speaker` when given
        and on its own speaker when None; False when no unrevoked device has that id. Raises
        psycopg.errors.CheckViolation for a blank host, an entity id that is not a `media_player`, or a device that
        takes controls; DatabaseUnavailable."""
        async with self._database.connection() as conn:
            cur = await conn.execute(
                "UPDATE devices SET esphome_host = %s, room_speaker = %s WHERE id = %s AND revoked_at IS NULL "
                "RETURNING id",
                (host, room_speaker, device_id),
            )
            found = await cur.fetchone() is not None
        logs.info(log, "devices.satellite_set", device=device_id, found=found, room_speaker=room_speaker is not None)
        return found

    async def set_house(self, device_id: int) -> bool:
        """Make the unrevoked device `device_id` the household's Home Assistant, which may hand in wakes; False when no
        unrevoked device has that id. Raises psycopg.errors.CheckViolation for a satellite, a Discord server
        or a device that takes controls; DatabaseUnavailable."""
        async with self._database.connection() as conn:
            cur = await conn.execute("UPDATE devices SET house = true WHERE id = %s AND revoked_at IS NULL RETURNING id",
                                     (device_id,))
            found = await cur.fetchone() is not None
        logs.info(log, "devices.house_set", device=device_id, found=found)
        return found

    async def set_discord_server(self, device_id: int, guild_id: int, home_channel_id: int) -> bool:
        """Make the unrevoked device a household's Discord server; False when no unrevoked device has that id. Raises
        psycopg.errors.UniqueViolation when another unrevoked device already has that server;
        psycopg.errors.CheckViolation for a device that takes controls; DatabaseUnavailable."""
        async with self._database.connection() as conn:
            cur = await conn.execute(
                "UPDATE devices SET discord_guild_id = %s, discord_home_channel_id = %s "
                "WHERE id = %s AND revoked_at IS NULL RETURNING id",
                (guild_id, home_channel_id, device_id),
            )
            found = await cur.fetchone() is not None
        logs.info(log, "devices.discord_server_set", device=device_id, found=found)
        return found

    async def add(self, household_id: int, name: str, place: str, audience: Audience, medium: Medium,
                  kind: Kind, remembers: bool = True, capabilities: frozenset[Capability] = frozenset()
                  ) -> tuple[Device, str]:
        """A new device, remembered unless `remembers` is false, with the `capabilities` it is registered with, and its
        token, which is returned here once and stored only as its SHA-256. Raises UnknownHousehold;
        psycopg.errors.CheckViolation for `controls` on a device that is not a text screen; DatabaseUnavailable."""
        token = secrets.token_urlsafe(32)
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "INSERT INTO devices (household_id, name, place, audience, medium, kind, remembers, token_sha256, "
                    "capabilities) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "RETURNING id, household_id, name, place, audience, medium, kind, remembers",
                    (household_id, name, place, audience, medium, kind, remembers, token_hash(token),
                     sorted(capabilities)),
                )
                row = await cur.fetchone()
        except psycopg.errors.ForeignKeyViolation as e:
            raise UnknownHousehold(household_id) from e
        assert row is not None
        device = _device(row)
        logs.info(log, "devices.added", device=device.id, household=household_id)
        return device, token

    async def set_controls(self, device_id: int, takes: bool) -> bool:
        """Say whether the unrevoked device `device_id` takes touch controls (the `controls` capability); False when no
        unrevoked device has that id. Raises psycopg.errors.CheckViolation for a device that is not a text screen
        (a satellite, a Discord server, the house, or spoken); DatabaseUnavailable."""
        async with self._database.connection() as conn:
            cur = await conn.execute(
                "UPDATE devices SET capabilities = CASE WHEN %s THEN ARRAY['controls'] ELSE '{}' END "
                "WHERE id = %s AND revoked_at IS NULL RETURNING id",
                (takes, device_id),
            )
            found = await cur.fetchone() is not None
        logs.info(log, "devices.controls_set", device=device_id, found=found, takes=takes)
        return found

    async def revoke(self, device_id: int) -> bool:
        """Revoke the device now, so its token signs in nothing; False when no unrevoked device has that id. Raises
        DatabaseUnavailable."""
        async with self._database.connection() as conn:
            cur = await conn.execute(
                "UPDATE devices SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL RETURNING id",
                (device_id,),
            )
            revoked = await cur.fetchone() is not None
        logs.info(log, "devices.revoked", device=device_id, revoked=revoked)
        return revoked


def _device(row: tuple[Any, ...]) -> Device:
    return Device(row[0], row[1], row[2], row[3], _AUDIENCES[row[4]], _MEDIA[row[5]], _KINDS[row[6]], row[7])


def _capabilities(stored: list[str]) -> frozenset[Capability]:
    return frozenset(_CAPABILITIES[c] for c in stored)

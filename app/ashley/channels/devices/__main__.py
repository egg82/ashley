"""`python -m ashley.channels.devices add HOUSEHOLD_ID NAME --place P --audience {household,present} --medium
{spoken,text} --kind {command,chat,brainstorm} [--not-remembered]` | `revoke DEVICE_ID` | `satellite DEVICE_ID --host H
[--room-speaker media_player.X]` | `discord DEVICE_ID GUILD_ID HOME_CHANNEL_ID` | `house DEVICE_ID` | `voice-enrol DEVICE_ID PERSON_ID
[--wakes N] [--minutes M]` | `voice-forget PERSON_ID`, against DATABASE_URL.

`satellite` makes a device a voice satellite reached at its ESPHome host, its reply played on the room speaker when one
is named and on its own speaker otherwise; run it again to change either (leaving out `--room-speaker` clears it).

`discord` makes a device a household's Discord server: `GUILD_ID` is Discord's id for the server (Developer Mode, Copy
Server ID) and `HOME_CHANNEL_ID` the text channel she calls home (Copy Channel ID). She answers a mention or a reply to
her in any channel of that server. A server belongs to one unrevoked device; run it again to change either id. The
Discord singleton reads the servers for each message, so a change applies at once.

`house` makes a device the household's Home Assistant, the one device whose token may hand in wakes
(`/api/wakes`). A satellite or a Discord server cannot be the house.

`voice-enrol` arms a satellite to enrol a person of its household from its next N wakes (default 6) within M
minutes (default `enrol_minutes` in `voice.json`): each of those wakes stores its voiceprint for them and is answered
as usual. Run it again to replace the enrolment. `voice-forget` deletes every voiceprint of a person, and any
enrolment armed for them, and prints how many prints went.

`add --not-remembered` registers a device whose conversations are never written into memory (the eval harness, test
devices); without it they are.

`add` prints the new device's id and its token. The token is shown only then and never stored, so copy it to the
device straight away; a lost token means revoking the device and adding another. Exit status: 0 done, 1 an unknown
household or device, a Discord server another unrevoked device has, a device and person not of one household, or no
database, 2 usage."""

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from typing import get_args

import psycopg

from ... import logs
from ...conversations.model import Kind
from ...db.database import DatabaseUnavailable
from ...db.pool import PoolDatabase
from ...settings import from_env
from ..model import Audience, Medium
from ..postgres_devices import PostgresDevices, UnknownHousehold
from ..voice import config as voice_config
from ..voice.postgres_voices import PostgresVoices
from ..voice.voices import UnknownEnrolee, Voices, VoicesUnavailable


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="python -m ashley.channels.devices")
    commands = top.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="sign a new shared device in; prints its id and token once")
    add.add_argument("household_id", type=int)
    add.add_argument("name")
    add.add_argument("--place", required=True)
    add.add_argument("--audience", required=True, choices=[a for a in get_args(Audience) if a != "owner"])
    add.add_argument("--medium", required=True, choices=get_args(Medium))
    add.add_argument("--kind", required=True, choices=get_args(Kind))
    add.add_argument("--not-remembered", action="store_true",
                     help="never write this device's conversations into memory (eval and test devices)")
    revoke = commands.add_parser("revoke", help="stop a device's token signing in")
    revoke.add_argument("device_id", type=int)
    satellite = commands.add_parser("satellite", help="make a device a voice satellite, or change its host or speaker")
    satellite.add_argument("device_id", type=int)
    satellite.add_argument("--host", required=True, help="its ESPHome host name or IP")
    satellite.add_argument("--room-speaker", help="a Home Assistant media_player entity id to play her reply on")
    discord = commands.add_parser("discord", help="make a device a household's Discord server, or change it")
    discord.add_argument("device_id", type=int)
    discord.add_argument("guild_id", type=int, help="Discord's id for the server")
    discord.add_argument("home_channel_id", type=int, help="Discord's id for her home text channel in it")
    house = commands.add_parser("house", help="make a device the household's Home Assistant, which hands in wakes")
    house.add_argument("device_id", type=int)
    enrol = commands.add_parser("voice-enrol", help="enrol a person's voice from a satellite's next wakes")
    enrol.add_argument("device_id", type=int)
    enrol.add_argument("person_id", type=int)
    enrol.add_argument("--wakes", type=int, default=6, help="how many wakes to enrol from (default 6)")
    enrol.add_argument("--minutes", type=float, help="how long the enrolment lasts (default from voice.json)")
    forget = commands.add_parser("voice-forget", help="delete every voiceprint of a person")
    forget.add_argument("person_id", type=int)
    return top


async def run(devices: PostgresDevices, voices: Voices, args: argparse.Namespace) -> int:
    """Carry out one parsed command and print its outcome; the exit status."""
    try:
        if args.command.startswith("voice-"):
            return await _voice(voices, args)
        if args.command == "add":
            device, token = await devices.add(args.household_id, args.name, args.place, args.audience, args.medium,
                                              args.kind, not args.not_remembered)
            print(f"device {device.id}")
            print(f"token {token}")
            return 0
        if args.command == "satellite":
            return await _satellite(devices, args)
        if args.command == "discord":
            return await _discord(devices, args)
        if args.command == "house":
            return await _house(devices, args)
        if await devices.revoke(args.device_id):
            print(f"device {args.device_id} revoked")
            return 0
        print(f"no unrevoked device {args.device_id}", file=sys.stderr)
        return 1
    except UnknownHousehold:
        print(f"no household {args.household_id}", file=sys.stderr)
        return 1
    except (DatabaseUnavailable, VoicesUnavailable):
        print("no database connection", file=sys.stderr)
        return 1


async def _voice(voices: Voices, args: argparse.Namespace) -> int:
    if args.command == "voice-forget":
        print(f"{await voices.forget(args.person_id)} voiceprints of person {args.person_id} forgotten")
        return 0
    minutes = voice_config.load().enrol_minutes if args.minutes is None else args.minutes
    try:
        await voices.arm(args.device_id, args.person_id, args.wakes, datetime.now(UTC) + timedelta(minutes=minutes))
    except UnknownEnrolee:
        print(f"no unrevoked device {args.device_id} with person {args.person_id} in its household", file=sys.stderr)
        return 1
    print(f"device {args.device_id} enrols person {args.person_id} from its next {args.wakes} wakes "
          f"within {minutes:g} minutes")
    return 0


async def _satellite(devices: PostgresDevices, args: argparse.Namespace) -> int:
    try:
        found = await devices.set_satellite(args.device_id, args.host, args.room_speaker)
    except psycopg.errors.CheckViolation:
        print("--host must not be blank and --room-speaker must be a media_player entity id", file=sys.stderr)
        return 2
    if found:
        print(f"device {args.device_id} is a satellite")
        return 0
    print(f"no unrevoked device {args.device_id}", file=sys.stderr)
    return 1


async def _house(devices: PostgresDevices, args: argparse.Namespace) -> int:
    try:
        found = await devices.set_house(args.device_id)
    except psycopg.errors.CheckViolation:
        print("a satellite or a Discord server cannot be the house", file=sys.stderr)
        return 2
    if found:
        print(f"device {args.device_id} is the house")
        return 0
    print(f"no unrevoked device {args.device_id}", file=sys.stderr)
    return 1


async def _discord(devices: PostgresDevices, args: argparse.Namespace) -> int:
    try:
        found = await devices.set_discord_server(args.device_id, args.guild_id, args.home_channel_id)
    except psycopg.errors.UniqueViolation:
        print(f"another device already is server {args.guild_id}", file=sys.stderr)
        return 1
    if found:
        print(f"device {args.device_id} is Discord server {args.guild_id}, home channel {args.home_channel_id}")
        return 0
    print(f"no unrevoked device {args.device_id}", file=sys.stderr)
    return 1


async def _main(args: argparse.Namespace) -> int:
    database = PoolDatabase(from_env().database_url)
    await database.open()
    try:
        return await run(PostgresDevices(database), PostgresVoices(database), args)
    finally:
        await database.close()


def main(argv: list[str]) -> int:
    args = parser().parse_args(argv)
    if args.command == "add" and not (args.name.strip() and args.place.strip()):
        print("NAME and --place must not be blank", file=sys.stderr)
        return 2
    if args.command == "discord" and min(args.guild_id, args.home_channel_id) <= 0:
        print("GUILD_ID and HOME_CHANNEL_ID must be Discord ids", file=sys.stderr)
        return 2
    if args.command == "voice-enrol" and (args.wakes < 1 or (args.minutes is not None and args.minutes <= 0)):
        print("--wakes and --minutes must be positive", file=sys.stderr)
        return 2
    logs.setup()
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

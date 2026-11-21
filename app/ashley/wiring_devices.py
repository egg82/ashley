"""What belongs to a device, wired at start: its sign-in, its touch controls, the clips it plays and the voices it knows.
Called by `ashley.wiring.wire`."""

from . import services
from .channels.devices import Devices
from .channels.kiosk.device_controls import DeviceControls
from .channels.kiosk.postgres_device_controls import PostgresDeviceControls
from .channels.postgres_devices import PostgresDevices
from .channels.voice import config as voice_config
from .channels.voice.clips import Clips
from .channels.voice.postgres_clips import PostgresClips
from .channels.voice.postgres_voices import PostgresVoices
from .channels.voice.voices import Voices
from .db.database import Database


def wire_devices() -> None:
    database = services.get(Database)
    services.register(Devices, PostgresDevices(database))
    services.register(DeviceControls, PostgresDeviceControls(database))
    services.register(Clips, PostgresClips(database, voice_config.load().clip_retention_s))
    services.register(Voices, PostgresVoices(database))

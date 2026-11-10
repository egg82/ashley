"""The adapter under test over the stand-in, and a small furnished house."""

from __future__ import annotations

import socket

import httpx2
from ashley.home_assistant.client import connect
from ashley.home_assistant.ha_house import HaHouse
from ashley.home_assistant.house_settings import load as load_settings
from hag_state_support import TOKEN, Ha


def client(ha: Ha, token: str | None = None) -> httpx2.AsyncClient:
    return connect(ha.url, token or ha.token).http


def make_house(ha: Ha, token: str | None = None) -> HaHouse:
    return HaHouse(connect(ha.url, token or ha.token), load_settings())


def dead_house() -> HaHouse:
    """A house whose address nothing listens on."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return HaHouse(connect(f"http://127.0.0.1:{port}", TOKEN), load_settings())


def furnish(ha: Ha) -> None:
    """A small house: two areas (one floored, one aliased), devices, lights with and without registry rows."""
    ground = ha.floor("Ground floor")
    ha.area("Living room", aliases=("lounge",), floor=ground)
    ha.area("Kitchen")
    ha.entry("hue", "Hue bridge")
    ha.device("Hue lamp", area="living_room", entries=("entry_hue_bridge",), manufacturer="Signify", model="LCT015", version="1.2")
    ha.add("light.reading_lamp", "off", "Reading lamp", device="dev_hue_lamp", aliases=[None, "book light"], exposed=True)
    ha.add("light.kitchen_strip", "on", "Kitchen strip", area="kitchen")
    ha.add("sensor.attic_temperature", "17.5", "Attic temperature", unit_of_measurement="C", registry=False, changed=None)

"""Who the money tools are offered to (`channels.audience.owner_alone`, `channels.turn_tools.for_turn`): only where the
channel names the speaker and the reply reaches them alone, read from the Inbound each adapter really builds. A
person's web chat, their bench talk and their Discord DM are; a satellite, the hallway tablet and a household's
Discord channel are not, even with a voice match or a known author. And never while connections cannot be opened."""

from collections.abc import Iterator
from dataclasses import replace
import pytest
from ashley import services
from ashley.api import bench_talk, chat, kiosk
from ashley.api.models import ChatRequest
from ashley.channels.audience import owner_alone
from ashley.channels.discord.message import Message
from ashley.channels.discord.route import decide
from ashley.channels.model import Device, DiscordServer, Inbound
from ashley.channels.turn_tools import for_turn, sources
from ashley.connections.connections import Connections, NullConnections
from ashley.people.model import Person
from ashley.signin.model import SignedIn
from ashley.tools.composite import CompositeTools
from ashley.tools.money import MoneyTools

ALANA = Person(1, 10, "Alana")
ELODIE = Person(2, 10, "Elodie")
BODY = ChatRequest(text="what did we spend on groceries?")
HALLWAY = Device(5, 10, "hallway", "hallway", "present", "text", "chat")
SERVER = DiscordServer(Device(6, 10, "server", "discord", "household", "text", "chat"), 900, 901)


def _discord(guild: int | None) -> Inbound:
    message = Message(id=1, channel_id=77, guild_id=guild, author_id=55, author_is_bot=False, content="<@2> money?",
                      mentions_me=True, replies_to_me=False)
    got = decide(message, 2, {SERVER.guild_id: SERVER}, ALANA)
    assert isinstance(got, Inbound)
    return got


def _satellite(heard_as: int | None) -> Inbound:
    return Inbound(household_id=10, thread="device:7", text="money?", kind="command", medium="spoken",
                   audience="present", speaker_id=None, shared=True, place="kitchen", channel="voice", heard_as=heard_as)


OWNER_ALONE = {
    "web chat": chat.inbound_from(SignedIn(3, ALANA), BODY),
    "bench talk": bench_talk.inbound_for(SignedIn(3, ALANA), 4, BODY),
    "discord dm": _discord(None),
}
SHARED = {
    "hallway tablet": kiosk.inbound_from(HALLWAY, BODY),
    "satellite": _satellite(None),
    "satellite with a voice match": _satellite(1),
    "household discord channel": _discord(SERVER.guild_id),
}


@pytest.mark.parametrize("name", OWNER_ALONE)
def test_a_channel_that_is_the_speakers_alone_is_owner_alone(name: str) -> None:
    assert owner_alone(OWNER_ALONE[name])


@pytest.mark.parametrize("name", SHARED)
def test_a_shared_channel_is_not_owner_alone(name: str) -> None:
    assert not owner_alone(SHARED[name])


WEB = OWNER_ALONE["web chat"]
ONE_FIELD_OFF = {"no speaker": replace(WEB, speaker_id=None), "household audience": replace(WEB, audience="household"),
                 "present audience": replace(WEB, audience="present"), "shared": replace(WEB, shared=True),
                 "on a device's screen": replace(WEB, device_id=5)}


@pytest.mark.parametrize("name", ONE_FIELD_OFF)
def test_each_field_alone_takes_it_away(name: str) -> None:
    assert owner_alone(WEB)
    assert not owner_alone(ONE_FIELD_OFF[name])


@pytest.fixture(autouse=True)
def no_connections() -> Iterator[None]:
    services.unregister(Connections)
    yield
    services.unregister(Connections)


class Opening(NullConnections):
    def can_open(self) -> bool:
        return True


def _money(inbound: Inbound) -> MoneyTools | None:
    found = sources(inbound).get("money")
    return found if isinstance(found, MoneyTools) else None


@pytest.mark.parametrize("name", OWNER_ALONE)
def test_money_is_offered_where_the_reply_is_theirs_alone(name: str) -> None:
    services.register(Connections, Opening())
    assert _money(OWNER_ALONE[name]) is not None


@pytest.mark.parametrize("name", SHARED)
def test_money_is_never_offered_on_a_shared_channel(name: str) -> None:
    services.register(Connections, Opening())
    assert _money(SHARED[name]) is None


def test_money_is_not_offered_while_connections_cannot_be_opened() -> None:
    assert not services.get(Connections).can_open()
    assert _money(OWNER_ALONE["web chat"]) is None


def test_a_turn_offering_money_keeps_the_everyday_tools_first() -> None:
    services.register(Connections, Opening())
    offered = for_turn(OWNER_ALONE["discord dm"])
    assert isinstance(offered, CompositeTools)


def test_money_is_offered_to_a_second_member_in_their_own_web_chat() -> None:
    services.register(Connections, Opening())
    assert _money(chat.inbound_from(SignedIn(4, ELODIE), BODY)) is not None

"""Money is offered on a household member's own web chat, whoever of them connected Sure."""

import pytest
from ashley import services
from ashley.api import chat
from ashley.api.models import ChatRequest
from ashley.channels.turn_tools import sources
from ashley.connections.connections import Connections
from ashley.people.model import Person
from ashley.signin.model import SignedIn
from ashley.tools.money import MoneyTools
from money_support import HeldConnections

ALANA = Person(1, 10, "Alana")
ELODIE = Person(2, 10, "Elodie")
BODY = ChatRequest(text="how are we doing on money?")


@pytest.mark.parametrize("who", [ALANA, ELODIE], ids=["the first member", "the second member"])
def test_a_members_web_chat_is_offered_the_money_tools(who: Person) -> None:
    held = HeldConnections()
    held.connect(10)
    services.register(Connections, held)
    assert isinstance(sources(chat.inbound_from(SignedIn(3, who), BODY)).get("money"), MoneyTools)


def test_the_second_members_web_chat_is_not_offered_money_when_the_household_has_no_connection_key() -> None:
    assert sources(chat.inbound_from(SignedIn(3, ELODIE), BODY)).get("money") is None

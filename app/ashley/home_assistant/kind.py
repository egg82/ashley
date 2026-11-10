"""Home Assistant as a connection kind: the household's house, checked by `GET /api/`."""

from collections.abc import Mapping
from typing import Any

from .. import services
from ..connections.kinds import CatalogueUnavailable, ConnectionKind, Refusal
from ..connections.model import CatalogueAction, CatalogueEntity, Catalogued, Opened
from ..connections.settings import ActionList, EntityList, EntityListPerAction, Setting
from .homes import SCHEMES, HomeAssistantFailed, Homes, HomesUnavailable, Reason
from .house import HouseUnavailable
from .house_values import CONSEQUENTIAL, HOUSEHOLD_READS, READS, SERVICE_READS


_REFUSED: dict[Reason, Refusal] = {"refused": "key_refused", "unreachable": "unreachable",
                                   "not_home_assistant": "wrong_service"}


async def _check(base: str, token: str, person_id: int) -> Refusal | None:
    try:
        await services.get(Homes).check(base, token)
    except HomeAssistantFailed as e:
        return _REFUSED[e.reason]
    return None


def _device_class(attributes: Mapping[str, Any]) -> str | None:
    value = attributes.get("device_class")
    return value if isinstance(value, str) else None


async def _catalogue(opened: Opened) -> Catalogued:
    """What the household's house has now: its things and its actions."""
    try:
        home = await services.get(Homes).of(opened.connection.household_id)
        if home is None:
            raise CatalogueUnavailable("the household has no house")
        states, actions = await home.house.states(), await home.house.actions()
    except (HomesUnavailable, HouseUnavailable) as e:
        raise CatalogueUnavailable("the house did not answer") from e
    return Catalogued(tuple(CatalogueEntity(s.id, s.name, s.domain, _device_class(s.attributes)) for s in states),
                      tuple(CatalogueAction(a.name, a.name.partition(".")[0], a.response == "only") for a in actions))


SETTINGS = (
    Setting(HOUSEHOLD_READS, EntityListPerAction(("todo.get_items",), ("todo",)), "taint"),
    Setting(SERVICE_READS, ActionList(("script", "weather")), "taint"),
    Setting(READS, ActionList(("script",)), "read"),
    Setting(CONSEQUENTIAL, EntityList(()), "tier"))

HOME_ASSISTANT = ConnectionKind(
    name="home_assistant", title="Home Assistant", what="the house",
    blurb="Let her see and run the household’s house: its lights and rooms, who is home, and the automations you "
          "approve on a bench.",
    connected="Connected. She reaches this household’s house now.",
    removed="Removed. She can’t reach the house now.",
    holders=frozenset({"household"}), schemes=SCHEMES, address_placeholder="http://homeassistant.local:8123",
    secret_field="token", secret_label="Long-lived access token, from your profile in Home Assistant",
    secret_noun="token", check=_check,
    ports=frozenset({"house"}), settings=SETTINGS, catalogue=_catalogue,
    refusals={
        "bad_url": "the address is an http or https address of Home Assistant, with nothing after it but a path",
        "key_refused": "Home Assistant turned that token away; make a long-lived one on your profile there",
        "unreachable": "nothing answered at that address in time",
        "wrong_service": "what answered at that address is not Home Assistant"})

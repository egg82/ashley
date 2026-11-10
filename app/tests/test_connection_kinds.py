"""The registry of connection kinds: what each adapter declares, how an address is judged, and what an empty registry
allows."""

import pytest
from ashley import services
from ashley.connections.kinds import ConnectionKinds
from ashley.wiring import CONNECTION_KINDS


pytestmark = pytest.mark.usefixtures("connection_kinds_wired")


def test_the_adapters_declare_their_kinds_in_panel_order() -> None:
    assert [k.name for k in CONNECTION_KINDS] == ["home_assistant", "sure", "gitlab", "github", "herdr", "google"]
    assert [k.default_holder == "person" for k in CONNECTION_KINDS] == [False, False, True, True, True, True]


def test_an_address_is_judged_by_the_kinds_own_schemes() -> None:
    kinds = services.get(ConnectionKinds)
    sure, home, github = kinds.get("sure"), kinds.get("home_assistant"), kinds.get("github")
    assert sure is not None and home is not None and github is not None
    assert sure.base_url("http://money.test") is None and sure.base_url("https://money.test/") == "https://money.test"
    assert home.base_url("http://ha.test:8123") == "http://ha.test:8123" and home.base_url(None) is None
    assert github.base_url(None) == "https://api.github.com" and github.base_url("https://elsewhere.test") == github.base_url(None)


def test_an_unregistered_name_is_no_kind_and_not_personal() -> None:
    kinds = services.get(ConnectionKinds)
    assert kinds.get("bitbucket") is None and not kinds.is_personal("bitbucket") and kinds.is_personal("gitlab")


def test_the_empty_registry_is_the_null_object() -> None:
    services.unregister(ConnectionKinds)
    assert services.get(ConnectionKinds).all() == ()


def test_two_kinds_may_not_share_a_name() -> None:
    first = CONNECTION_KINDS[0]
    with pytest.raises(ValueError):
        ConnectionKinds((first, first))


def test_each_port_is_implemented_by_its_adapters_kinds_in_registration_order() -> None:
    kinds = services.get(ConnectionKinds)
    assert [k.name for k in kinds.of_port("house")] == ["home_assistant"]
    assert [k.name for k in kinds.of_port("ledger")] == ["sure"]
    assert [k.name for k in kinds.of_port("code_host")] == ["gitlab", "github"]
    assert [k.name for k in kinds.of_port("herdr")] == ["herdr"]

"""The herdr kind's address (the fingerprint rides in the fragment), its registration, the settings and tunables."""

import pytest
from ashley import services, wiring
from ashley.connections import address
from ashley.herdr import config
from ashley.herdr.bridge import Bridge
from ashley.herdr.http_bridge import HttpBridge
from ashley.herdr.kind import HERDR
from ashley.herdr.model import Access, BridgeFailed
from ashley.herdr.register import register
from ashley.settings import Settings, from_env

PIN = "ab" * 32
HTTPS = frozenset({"https"})


def test_a_pinned_address_ends_in_the_fingerprint_and_comes_back_lowercase() -> None:
    assert address.base_url(f" https://vm.test:7843#sha256={PIN.upper()} ", HTTPS, pinned=True) == \
        f"https://vm.test:7843#sha256={PIN}"


@pytest.mark.parametrize("typed", ["https://vm.test:7843", f"https://vm.test:7843#sha256={PIN[:-2]}",
                                   f"https://vm.test:7843#sha1={PIN}", f"http://vm.test:7843#sha256={PIN}",
                                   f"#sha256={PIN}", f"https://vm.test:7843#sha256={PIN}#x",
                                   f"https://vm.test:7843?q=1#sha256={PIN}", f"https://u:p@vm.test#sha256={PIN}"])
def test_a_pinned_address_without_a_good_fingerprint_is_no_address(typed: str) -> None:
    assert address.base_url(typed, HTTPS, pinned=True) is None


def test_other_addresses_still_take_no_fragment() -> None:
    assert address.base_url(f"https://vm.test#sha256={PIN}", HTTPS) is None


def test_the_kind_is_personal_pinned_and_registered_before_google() -> None:
    assert (HERDR.name, HERDR.holders, HERDR.pinned, HERDR.secret_field) == ("herdr", frozenset({"person"}), True, "token")
    assert wiring.CONNECTION_KINDS[-2] is HERDR
    assert HERDR.base_url("http://vm.test") is None and HERDR.base_url(f"https://vm.test:7843#sha256={PIN}")


def test_the_access_of_a_stored_address_splits_the_pin_from_the_origin() -> None:
    assert Access.of(f"https://vm.test:7843#sha256={PIN}", "t", 3) == Access("https://vm.test:7843", PIN, "t", 3)


def test_an_address_without_a_pin_is_never_trusted() -> None:
    with pytest.raises(BridgeFailed) as caught:
        Access.of("https://vm.test:7843", "t", 3)
    assert caught.value.reason == "unexpected"


def test_the_shipped_tunables_load() -> None:
    assert config.load().timeout_s > 0


@pytest.mark.parametrize("data", [[], {}, {"timeout_s": 1, "start_timeout_s": 1}, {"timeout_s": 0, "start_timeout_s": 1,
                                  "response_max_bytes": 1}, {"timeout_s": 1, "start_timeout_s": 1, "response_max_bytes": 1.5},
                                  {"timeout_s": True, "start_timeout_s": 1, "response_max_bytes": 1},
                                  {"timeout_s": 1, "start_timeout_s": 1, "response_max_bytes": 1, "more": 1}])
def test_a_bad_config_is_refused(data: object) -> None:
    with pytest.raises(ValueError):
        config.parse(data)


def test_the_certificate_and_key_are_set_together() -> None:
    base = {"database_url": "postgresql://x", "build_version": "t"}
    with pytest.raises(ValueError, match="HERDR_CLIENT_CERT_FILE"):
        Settings(**base, herdr_client_cert_file="/c")
    with pytest.raises(ValueError, match="HERDR_CLIENT_CERT_FILE"):
        Settings(**base, herdr_client_key_file="/k")
    env = {"DATABASE_URL": "postgresql://x", "HERDR_CLIENT_CERT_FILE": " /c\n", "HERDR_CLIENT_KEY_FILE": "/k"}
    assert (from_env(env).herdr_client_cert_file, from_env(env).herdr_client_key_file) == ("/c", "/k")


def test_the_adapter_is_wired_only_with_a_certificate() -> None:
    services.unregister(Bridge)
    register("", "")
    assert not isinstance(services.get(Bridge), HttpBridge)
    register("/c", "/k")
    try:
        assert isinstance(services.get(Bridge), HttpBridge)
    finally:
        services.unregister(Bridge)

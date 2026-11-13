"""The connection-kind registry (Type Object): the four declared kinds, `ConnectionKinds` as the one list, a kind's
address rule and `address.base_url`."""

from dataclasses import replace

import pytest
from ashley.codehost.kinds import GITHUB, GITLAB
from ashley.connections import address
from ashley.connections.kinds import ConnectionKind, ConnectionKinds
from ashley.google.kind import GOOGLE
from ashley.herdr.kind import HERDR
from ashley.home_assistant.kind import HOME_ASSISTANT
from ashley.inference.compatible import KIND as COMPATIBLE
from ashley.inference.kinds import KEYED
from ashley.mail.resources import mailboxes
from ashley.sure.kind import SURE
from ashley.channels.discord.token_kind import KIND as DISCORD
from ashley.files.store_kind import KIND as FILES
from ashley.inference.wyoming_kind import KIND as WYOMING
from ashley.tools.search_connection import KIND as SEARXNG
from ashley.wiring import CONNECTION_KINDS
from connection_kinds_blind_support import KIND_NAMES, kind_named

REASONS = ("bad_url", "key_refused", "unreachable", "wrong_service")
PROVIDERS = ("anthropic", "openai", "gemini", "elevenlabs")


async def accepts(base_url: str, secret: str, person_id: int) -> None:
    return None


def custom(name: str, personal: bool = False, fixed: str | None = None) -> ConnectionKind:
    return ConnectionKind(name=name, title=name.title(), what="music", blurb="b", connected="c", removed="r",
                          holders=frozenset({"person"} if personal else {"household"}), schemes=frozenset({"https"}), address_placeholder="https://x.test",
                          secret_field="token", secret_label="Token", secret_noun="token", check=accepts,
                          refusals={r: f"{r} text" for r in REASONS}, ports=frozenset(), fixed_address=fixed)


def test_the_four_services_and_the_herdr_bridge_are_the_registered_kinds() -> None:
    assert sorted(k.name for k in CONNECTION_KINDS) == sorted((*KIND_NAMES, "herdr", "google", *PROVIDERS,
                                                                    "openai_compatible", "wyoming", "searxng", "discord", "files"))
    assert {k.name: k for k in CONNECTION_KINDS} == {"sure": SURE, "home_assistant": HOME_ASSISTANT, "gitlab": GITLAB,
                                                     "github": GITHUB, "herdr": HERDR, "google": replace(GOOGLE, resources=mailboxes),
                                                     **{k.kind.name: k.kind for k in KEYED}, COMPATIBLE.name: COMPATIBLE,
                                                     WYOMING.name: WYOMING, SEARXNG.name: SEARXNG, DISCORD.name: DISCORD, FILES.name: FILES}


@pytest.mark.parametrize(("name", "personal", "field"), [
    ("sure", False, "api_key"), ("home_assistant", False, "token"), ("gitlab", True, "token"), ("github", True, "token")])
def test_a_code_host_is_personal_and_the_others_are_the_households(name: str, personal: bool, field: str) -> None:
    declared = kind_named(name)
    assert (declared.default_holder == "person") is personal and declared.secret_field == field


@pytest.mark.parametrize("name", KIND_NAMES)
def test_every_kind_has_words_for_a_person_and_a_refusal_text_for_each_reason(name: str) -> None:
    declared = kind_named(name)
    for words in (declared.title, declared.what, declared.blurb, declared.connected, declared.removed,
                  declared.secret_label, declared.secret_noun):
        assert words.strip()
    assert all(declared.refusals[r].strip() for r in REASONS)


def test_only_github_has_one_address() -> None:
    assert {k.name for k in CONNECTION_KINDS if k.fixed_address is not None} == {"github", "google", "discord", *PROVIDERS}
    assert GITHUB.fixed_address is not None and GITHUB.fixed_address.startswith("https://")


def test_the_registry_lists_its_kinds_in_order_and_finds_them_by_name() -> None:
    a, b, c = custom("alpha"), custom("beta", personal=True), custom("gamma")
    kinds = ConnectionKinds((b, a, c))
    assert kinds.all() == (b, a, c)
    assert kinds.get("alpha") is a and kinds.get("beta") is b and kinds.get("delta") is None
    assert [kinds.is_personal(n) for n in ("alpha", "beta")] == [False, True]


def test_two_kinds_may_not_share_a_name() -> None:
    with pytest.raises(ValueError):
        ConnectionKinds((custom("alpha"), custom("alpha", personal=True)))


def test_an_unregistered_name_is_not_personal() -> None:
    assert ConnectionKinds((custom("alpha", personal=True),)).is_personal("nothing") is False


def test_the_null_registry_has_no_kinds() -> None:
    null = ConnectionKinds.null()
    assert null.all() == () and null.get("sure") is None and null.is_personal("gitlab") is False


@pytest.mark.parametrize(("name", "typed", "expected"), [
    ("sure", "https://money.example", "https://money.example"),
    ("sure", "https://money.example/app", "https://money.example/app"),
    ("sure", "http://money.example", None),
    ("sure", "money.example", None),
    ("sure", None, None),
    ("home_assistant", "http://ha.example:8123", "http://ha.example:8123"),
    ("home_assistant", "https://ha.example", "https://ha.example"),
    ("home_assistant", "ftp://ha.example", None),
    ("gitlab", "https://gitlab.example", "https://gitlab.example"),
    ("gitlab", "http://gitlab.example", None)])
def test_a_kind_takes_the_address_a_person_types_only_in_its_schemes(name: str, typed: str | None,
                                                                    expected: str | None) -> None:
    assert kind_named(name).base_url(typed) == expected


@pytest.mark.parametrize("typed", [None, "", "https://elsewhere.example", "http://elsewhere.example/x"])
def test_a_kind_with_one_address_is_reached_there_whatever_was_typed(typed: str | None) -> None:
    assert GITHUB.base_url(typed) == GITHUB.fixed_address


@pytest.mark.parametrize("typed", ["https://u:p@h.example", "https://u@h.example", "https://:p@h.example", "https://h.example/?a=1",
                                   "https://h.example/#frag", "https://", "https:///path", "https://h.example:99999",
                                   "https://h.example:0", "", "   "])
def test_an_address_with_credentials_query_fragment_no_host_or_a_bad_port_is_none(typed: str) -> None:
    assert address.base_url(typed, frozenset({"http", "https"})) is None


def test_an_address_keeps_its_path_and_drops_the_trailing_slash() -> None:
    schemes = frozenset({"https"})
    assert address.base_url("https://h.example/app", schemes) == "https://h.example/app"
    got = address.base_url("https://h.example/app/", schemes)
    assert got is not None and not got.endswith("/") and got.startswith("https://h.example/app")
    bare = address.base_url("https://h.example/", schemes)
    assert bare is not None and not bare.endswith("/")


def test_an_address_takes_only_the_schemes_it_is_given() -> None:
    assert address.base_url("http://h.example", frozenset({"https"})) is None
    assert address.base_url("http://h.example", frozenset({"http"})) == "http://h.example"
    assert address.base_url("https://h.example", frozenset({"http"})) is None
    assert address.base_url("http://h.example:8123", frozenset({"http", "https"})) == "http://h.example:8123"


def test_an_address_typed_with_surrounding_spaces_is_taken_without_them() -> None:
    assert address.base_url("  https://h.example/app  ", frozenset({"https"})) == "https://h.example/app"

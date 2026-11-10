"""The 0004 schema refuses bad rows on its own: an account's system and external id, one person per external id, an
account only for a person of its own household; a device's fields and its 32-byte token hash; a thread only for a
conversation of its own household. Each refusal has a control row that the same table accepts."""

import psycopg
import pytest
from conversations_support import person, scalar
from people_support import account, device, execute, home, sha256

CHECK = psycopg.errors.CheckViolation
UNIQUE = psycopg.errors.UniqueViolation
FOREIGN = psycopg.errors.ForeignKeyViolation


def test_a_valid_account_is_accepted(db_url: str) -> None:
    house = home(db_url)
    assert account(db_url, house, person(db_url, house), "home_assistant", "person.alana") > 0


@pytest.mark.parametrize(("system", "external_id"), [
    ("Home_assistant", "x"), ("1discord", "x"), ("home-assistant", "x"), ("", "x"), ("discord", ""),
    ("discord", "   "), ("discord", "\t\n"),
])
def test_an_account_with_a_bad_system_or_external_id_is_refused(db_url: str, system: str, external_id: str) -> None:
    house = home(db_url)
    with pytest.raises(CHECK):
        account(db_url, house, person(db_url, house), system, external_id)


def test_an_external_id_maps_to_at_most_one_person(db_url: str) -> None:
    house = home(db_url)
    account(db_url, house, person(db_url, house), "discord", "42")
    account(db_url, house, person(db_url, house), "home_assistant", "42")   # control: another system may reuse it
    with pytest.raises(UNIQUE):
        account(db_url, house, person(db_url, house), "discord", "42")


def test_one_person_may_have_several_accounts(db_url: str) -> None:
    house = home(db_url)
    alana = person(db_url, house)
    account(db_url, house, alana, "discord", "1")
    account(db_url, house, alana, "home_assistant", "person.alana")
    assert scalar(db_url, "SELECT count(*) FROM accounts WHERE person_id = %s", (alana,)) == 2


def test_an_account_cannot_name_a_person_of_another_household(db_url: str) -> None:
    house, other = home(db_url), home(db_url)
    theirs = person(db_url, other)
    with pytest.raises(FOREIGN):
        account(db_url, house, theirs, "discord", "99")


def test_a_valid_device_is_accepted(db_url: str) -> None:
    assert device(db_url, home(db_url), "tok") > 0


@pytest.mark.parametrize(("field", "value"), [
    ("name", " "), ("place", ""), ("audience", "owner"), ("audience", "everyone"), ("medium", "video"),
    ("kind", "memory"),
])
def test_a_device_with_a_bad_field_is_refused(db_url: str, field: str, value: str) -> None:
    house = home(db_url)
    fields = {"name": "tablet", "place": "hallway", "audience": "household", "medium": "text", "kind": "chat"}
    fields[field] = value
    with pytest.raises(CHECK):
        device(db_url, house, "tok", **fields)


@pytest.mark.parametrize("digest", [b"", b"\x00" * 31, b"\x00" * 33, b"plaintext-token"])
def test_a_device_token_hash_is_32_bytes(db_url: str, digest: bytes) -> None:
    house = home(db_url)
    with pytest.raises(CHECK):
        execute(db_url, "INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256) "
                        "VALUES (%s, 'a', 'b', 'present', 'spoken', 'command', %s)", (house, digest))


def test_two_devices_cannot_share_a_token(db_url: str) -> None:
    house = home(db_url)
    device(db_url, house, "same")
    with pytest.raises(UNIQUE):
        device(db_url, house, "same")
    assert sha256("same") != sha256("other")


def test_a_thread_cannot_point_at_another_households_conversation(db_url: str) -> None:
    house, other = home(db_url), home(db_url)
    theirs = int(scalar(db_url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                        (other,)))
    execute(db_url, "INSERT INTO conversation_threads (thread, household_id, conversation_id) VALUES ('ok', %s, %s)",
            (other, theirs))
    with pytest.raises(FOREIGN):
        execute(db_url, "INSERT INTO conversation_threads (thread, household_id, conversation_id) "
                        "VALUES ('bad', %s, %s)", (house, theirs))

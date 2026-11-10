"""Look keys and the two signed links: the page link a browser pod opens and the picture link a conversation hands out.
Each has its own purpose, so no token is good for another's check, a file link's included."""

import pytest
from ashley.files import links as file_links
from ashley.looks import links
from ashley.looks.keys import key_of

KEY = b"k" * 40
NOW = 1_000_000.0
GRANT = links.Grant(household_id=3, person_id=9, bench_id=12, piece_id=5, expires_at=int(NOW) + 100)
PICTURE = links.Picture(household_id=3, sha256="ab" * 32, media_type="image/jpeg", expires_at=int(NOW) + 100)


def test_a_look_key_is_under_the_look_prefix_the_household_and_the_hash() -> None:
    assert key_of(7, "cd" * 32) == "look/7/" + "cd" * 32


def test_two_households_keep_the_same_bytes_under_two_keys() -> None:
    assert key_of(1, "ab" * 32) != key_of(2, "ab" * 32)


def test_a_look_key_is_never_under_the_benchs_files_prefix() -> None:
    assert not key_of(7, "cd" * 32).startswith("bench/")


def test_a_page_token_carries_its_grant_back() -> None:
    assert links.check(KEY, links.mint(KEY, GRANT), NOW) == GRANT


def test_a_page_token_for_the_whole_bench_carries_no_piece() -> None:
    whole = links.Grant(3, 9, 12, None, int(NOW) + 100)
    assert links.check(KEY, links.mint(KEY, whole), NOW) == whole


def test_a_page_token_is_payload_dot_mac() -> None:
    assert links.mint(KEY, GRANT).count(".") == 1


def test_a_page_token_works_until_it_expires_and_not_after() -> None:
    token = links.mint(KEY, GRANT)
    assert links.check(KEY, token, GRANT.expires_at - 1) == GRANT
    assert links.check(KEY, token, GRANT.expires_at + 1) is None


def test_a_page_token_under_another_key_is_refused() -> None:
    assert links.check(b"j" * 40, links.mint(KEY, GRANT), NOW) is None


@pytest.mark.parametrize("junk", ["", ".", "abc", "a.b", "a.b.c", "....", "é.é", " "])
def test_malformed_tokens_are_none_not_errors(junk: str) -> None:
    assert links.check(KEY, junk, NOW) is None
    assert links.check_picture(KEY, junk, NOW) is None


def test_a_token_with_a_changed_payload_is_refused() -> None:
    other = links.mint(KEY, links.Grant(4, 9, 12, 5, int(NOW) + 100))
    payload, _ = links.mint(KEY, GRANT).split(".")
    _, mac = other.split(".")
    assert links.check(KEY, f"{payload}.{mac}", NOW) is None


def test_a_token_with_a_changed_mac_is_refused() -> None:
    payload, mac = links.mint(KEY, GRANT).split(".")
    flipped = ("A" if mac[0] != "A" else "B") + mac[1:]
    assert links.check(KEY, f"{payload}.{flipped}", NOW) is None


def test_a_picture_token_carries_its_picture_back() -> None:
    assert links.check_picture(KEY, links.mint_picture(KEY, PICTURE), NOW) == PICTURE


def test_a_picture_token_expires() -> None:
    token = links.mint_picture(KEY, PICTURE)
    assert links.check_picture(KEY, token, PICTURE.expires_at - 1) == PICTURE
    assert links.check_picture(KEY, token, PICTURE.expires_at + 1) is None


def test_a_picture_token_under_another_key_is_refused() -> None:
    assert links.check_picture(b"j" * 40, links.mint_picture(KEY, PICTURE), NOW) is None


def test_a_picture_token_is_no_page_token_and_a_page_token_no_picture_token() -> None:
    assert links.check(KEY, links.mint_picture(KEY, PICTURE), NOW) is None
    assert links.check_picture(KEY, links.mint(KEY, GRANT), NOW) is None


def test_a_file_link_is_no_look_link_of_either_kind() -> None:
    grant = file_links.Grant(3, "ab" * 32, "image/png", True, int(NOW) + 100)
    token = file_links.mint(KEY, grant).url.rsplit("/", 1)[-1]
    assert file_links.check(KEY, token, NOW) == grant
    assert links.check(KEY, token, NOW) is None
    assert links.check_picture(KEY, token, NOW) is None


def test_a_look_token_is_no_file_link() -> None:
    assert file_links.check(KEY, links.mint(KEY, GRANT), NOW) is None
    assert file_links.check(KEY, links.mint_picture(KEY, PICTURE), NOW) is None


def test_a_token_names_whose_bench_it_is_not_just_any_bench() -> None:
    a = links.mint(KEY, GRANT)
    b = links.mint(KEY, links.Grant(3, 10, 12, 5, GRANT.expires_at))
    assert a != b
    granted = links.check(KEY, b, NOW)
    assert granted is not None and granted.person_id == 10


def test_a_picture_token_names_household_and_hash() -> None:
    other = links.Picture(4, PICTURE.sha256, PICTURE.media_type, PICTURE.expires_at)
    granted = links.check_picture(KEY, links.mint_picture(KEY, other), NOW)
    assert granted is not None and (granted.household_id, granted.sha256) == (4, PICTURE.sha256)


def test_a_page_token_has_stopped_at_the_moment_it_ends() -> None:
    token = links.mint(KEY, GRANT)
    assert links.check(KEY, token, float(GRANT.expires_at)) is None


def test_a_picture_token_has_stopped_at_the_moment_it_ends() -> None:
    token = links.mint_picture(KEY, PICTURE)
    assert links.check_picture(KEY, token, float(PICTURE.expires_at)) is None

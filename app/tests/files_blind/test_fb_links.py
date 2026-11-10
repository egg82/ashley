"""Download links: HMAC-signed, expiring, naming the object and no file name; a forged, altered, expired or foreign-key
token fails `check`, and `window_end` gives every link made within one half-ttl window the same end."""

import dataclasses
import string

import pytest
from ashley.files import links
from ashley.files.links import Grant, check, mint, window_end
from files_blind_support import LINK_KEY, sha
from hypothesis import given, settings
from hypothesis import strategies as st

KEY = LINK_KEY.encode()
NOW = 1_800_000_000
GRANT = Grant(7, sha(b"abc"), "image/png", True, NOW + 100)


def token_of(grant: Grant = GRANT, key: bytes = KEY) -> str:
    link = mint(key, grant)
    assert link.url.startswith(links.PATH)
    return link.url[len(links.PATH):]


def test_a_minted_link_is_a_path_on_this_site_and_carries_the_grants_end() -> None:
    link = mint(KEY, GRANT)
    assert link.url.startswith("/api/files/") and link.expires_at == GRANT.expires_at


def test_a_token_is_one_url_safe_path_segment() -> None:
    token = token_of()
    assert token and set(token) <= set(string.ascii_letters + string.digits + "-_.=~")


def test_a_token_round_trips_to_its_grant_while_it_lasts() -> None:
    assert check(KEY, token_of(), NOW) == GRANT
    assert check(KEY, token_of(), NOW + 99) == GRANT


@pytest.mark.parametrize("later", [101, 1000, 10**6])
def test_a_token_fails_after_its_end(later: int) -> None:
    assert check(KEY, token_of(), NOW + later) is None


def test_every_field_of_the_grant_survives() -> None:
    for g in (dataclasses.replace(GRANT, inline=False), dataclasses.replace(GRANT, household_id=123456),
              dataclasses.replace(GRANT, media_type="application/pdf"), dataclasses.replace(GRANT, sha256=sha(b"zzz"))):
        assert check(KEY, token_of(g), NOW) == g


def test_a_token_made_under_another_key_fails() -> None:
    assert check(b"z" * 40, token_of(), NOW) is None


@pytest.mark.parametrize("token", ["", ".", "abc", "a.b", "a.b.c", "....", "%%%.%%%", "eyJ.", ".sig", " ", "a b.c d"])
def test_a_malformed_token_is_none_and_never_raises(token: str) -> None:
    assert check(KEY, token, NOW) is None


def test_every_single_character_change_of_a_token_fails() -> None:
    token = token_of()
    for i in range(len(token)):
        swapped = "A" if token[i] != "A" else "B"
        assert check(KEY, token[:i] + swapped + token[i + 1:], NOW) is None, i


def test_a_token_cut_short_or_extended_fails() -> None:
    token = token_of()
    assert check(KEY, token[:-1], NOW) is None
    assert check(KEY, token + "A", NOW) is None
    assert check(KEY, token[: token.index(".")], NOW) is None


def test_the_mac_of_one_grant_does_not_vouch_for_another_payload() -> None:
    a, b = token_of(), token_of(dataclasses.replace(GRANT, household_id=8))
    payload_a, mac_a = a.split(".", 1)
    payload_b, mac_b = b.split(".", 1)
    assert payload_a != payload_b
    assert check(KEY, f"{payload_b}.{mac_a}", NOW) is None
    assert check(KEY, f"{payload_a}.{mac_b}", NOW) is None


def test_a_token_carries_no_file_name_and_no_plain_hash() -> None:
    token = token_of(Grant(7, sha(b"abc"), "image/png", True, NOW + 100))
    assert ".png" not in token and "png" not in token.split(".")[1]


@settings(max_examples=40)
@given(h=st.integers(1, 10**9), data=st.binary(max_size=20), inline=st.booleans(), ttl=st.integers(1, 10**6),
       media=st.sampled_from(["image/png", "application/pdf", "text/plain", "application/zip"]))
def test_property_links_round_trip_within_the_window_and_fail_after(h: int, data: bytes, inline: bool, ttl: int, media: str) -> None:
    g = Grant(h, sha(data), media, inline, NOW + ttl)
    t = token_of(g)
    assert check(KEY, t, NOW) == g
    assert check(KEY, t, NOW + ttl - 1) == g
    assert check(KEY, t, NOW + ttl + 1) is None
    assert check(b"other-key-other-key-other-key-0000", t, NOW) is None


@settings(max_examples=40)
@given(now=st.floats(1e9, 4e9), ttl=st.integers(2, 100_000))
def test_property_a_link_lives_between_half_the_ttl_and_all_of_it(now: float, ttl: int) -> None:
    end = window_end(now, ttl)
    assert ttl / 2 - 1 <= end - now <= ttl + 1e-6


@settings(max_examples=40)
@given(now=st.floats(1e9, 4e9), ttl=st.integers(2, 100_000).filter(lambda t: t % 2 == 0))
def test_property_links_made_within_a_half_window_end_together_and_the_next_window_a_half_later(now: float, ttl: int) -> None:
    half = ttl // 2
    end = window_end(now, ttl)
    assert window_end(now + half, ttl) == end + half
    seen = {window_end(now + i * half / 4, ttl) for i in range(4)}
    assert seen <= {end, end + half}
    assert window_end(now, ttl) <= window_end(now + 1, ttl)


def test_window_end_is_stable_across_a_bench_read_and_the_next_one_moments_later() -> None:
    ends = [window_end(1_800_000_000 + s, 900) for s in range(0, 449)]
    assert len(set(ends)) <= 2
    assert window_end(1_800_000_000 + 450, 900) > window_end(1_800_000_000, 900)


def test_a_token_is_dead_at_the_instant_it_stops() -> None:
    assert check(KEY, token_of(), NOW + 99.999) == GRANT
    assert check(KEY, token_of(), NOW + 100) is None


def test_a_link_made_at_any_moment_of_a_window_lives_between_half_and_all_of_the_ttl() -> None:
    for s in range(0, 1800, 7):
        life = window_end(1_800_000_000 + s, 900) - (1_800_000_000 + s)
        assert 450 <= life <= 900, s

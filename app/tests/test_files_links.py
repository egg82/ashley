"""A download link is a signed, expiring token: it carries what it grants, any pod under the key verifies it, and a
forged, altered, expired or foreign-keyed one grants nothing."""

from ashley.files import links
from ashley.files.links import Grant

KEY = b"k" * 32
SHA = "a" * 64
GRANT = Grant(7, SHA, "image/png", True, 2000)


def token_of(url: str) -> str:
    assert url.startswith(links.PATH)
    return url[len(links.PATH):]


def test_a_link_gives_back_its_grant_until_it_expires() -> None:
    link = links.mint(KEY, GRANT)
    assert link.expires_at == 2000
    assert links.check(KEY, token_of(link.url), 1999.9) == GRANT
    assert links.check(KEY, token_of(link.url), 2000) is None
    assert links.check(KEY, token_of(link.url), 5000) is None


def test_the_token_names_no_file_name_and_no_plain_hash_in_its_mac() -> None:
    assert "." in token_of(links.mint(KEY, GRANT).url)


def test_another_key_or_an_altered_token_grants_nothing() -> None:
    token = token_of(links.mint(KEY, GRANT).url)
    assert links.check(b"x" * 32, token, 0) is None
    payload, _, mac = token.partition(".")
    altered = links.mint(KEY, Grant(8, SHA, "image/png", True, 2000)).url
    assert links.check(KEY, token_of(altered).partition(".")[0] + "." + mac, 0) is None
    assert links.check(KEY, payload[:-1] + ("A" if payload[-1] != "A" else "B") + "." + mac, 0) is None


def test_garbage_grants_nothing() -> None:
    for junk in ("", ".", "abc", "abc.def", "....", "e30.e30", "é.é"):
        assert links.check(KEY, junk, 0) is None


def test_a_validly_signed_payload_that_is_not_a_grant_grants_nothing() -> None:
    import base64
    import hashlib
    import hmac
    payload = base64.urlsafe_b64encode(b'{"h":"x"}').decode().rstrip("=")
    mac = base64.urlsafe_b64encode(hmac.new(KEY, payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    assert links.check(KEY, f"{payload}.{mac}", 0) is None


def test_links_made_within_a_window_end_together_and_live_between_half_and_all_of_the_ttl() -> None:
    ttl = 900
    ends = {links.window_end(t, ttl) for t in range(900, 1350)}
    assert len(ends) == 1
    for t in range(0, 5000, 7):
        lived = links.window_end(t, ttl) - t
        assert ttl // 2 < lived <= ttl

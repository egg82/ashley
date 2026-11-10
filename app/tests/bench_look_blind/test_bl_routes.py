"""The two routes: `GET /api/look/{token}` (a bench for the browser pod, the token its only credential) and
`GET /api/looks/{token}` (a kept picture, the picture link its only credential)."""

import logging
import time

import pytest
from ashley.looks import links
from ashley.looks.keys import key_of
from bench_look_blind_support import LINK_KEY, SHOT_BYTES, Rig, fields_of, log_text, rig, sha
from httpx2 import Response

KEY = LINK_KEY.encode()


def page_token(owner_household: int, person: int, bench: int, piece: int | None = None, ttl: int = 100) -> str:
    return links.mint(KEY, links.Grant(owner_household, person, bench, piece, int(time.time()) + ttl))


def picture_token(household: int, data: bytes = SHOT_BYTES, media: str = "image/jpeg", ttl: int = 100) -> str:
    return links.mint_picture(KEY, links.Picture(household, sha(data), media, int(time.time()) + ttl))


def page(r: Rig, token: str) -> Response:
    return r.client.get(f"/api/look/{token}")


def picture(r: Rig, token: str) -> Response:
    return r.client.get(f"/api/looks/{token}")


def test_a_valid_token_reads_the_bench_with_its_pieces_and_the_kinds(db_url: str) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        first, second = r.add_note(bench, "one"), r.add_note(bench, "two")
        got = page(r, page_token(r.w.alana.household_id, r.w.alana.person_id, bench))
        assert got.status_code == 200
        body = got.json()
        assert body["view"]["bench"]["id"] == bench
        assert [p["id"] for p in body["view"]["pieces"]] == [first, second]
        assert body["rules"]


def test_a_token_naming_a_piece_narrows_the_answer_to_that_piece(db_url: str) -> None:
    with rig(db_url) as r:
        w = r.w
        bench = r.new_bench()
        r.add_note(bench, "one")
        second = r.add_note(bench, "two")
        got = page(r, page_token(w.alana.household_id, w.alana.person_id, bench, second))
        assert got.status_code == 200
        assert [p["id"] for p in got.json()["view"]["pieces"]] == [second]


def test_the_answer_is_not_cached(db_url: str) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        got = page(r, page_token(r.w.alana.household_id, r.w.alana.person_id, bench))
        assert "no-store" in got.headers["cache-control"]


def test_the_token_is_the_only_credential_no_session_is_needed(db_url: str) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        token = page_token(r.w.alana.household_id, r.w.alana.person_id, bench)
    with rig(db_url, signed_in=False) as bare:
        assert page(bare, token).status_code == 200


@pytest.mark.parametrize("token", ["", "x", "a.b", "....", "%00", "a.b.c"])
def test_a_malformed_token_is_404_not_found(db_url: str, token: str) -> None:
    with rig(db_url) as r:
        got = page(r, token)
        assert got.status_code in (404, 405)
        if token and got.status_code == 404:
            assert got.json()["code"] == "not_found"


def test_a_forged_token_is_404_not_found(db_url: str) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        forged = links.mint(b"z" * 40, links.Grant(r.w.alana.household_id, r.w.alana.person_id, bench, None, int(time.time()) + 100))
        got = page(r, forged)
        assert got.status_code == 404 and got.json()["code"] == "not_found"


def test_an_expired_token_is_404_not_found(db_url: str) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        got = page(r, page_token(r.w.alana.household_id, r.w.alana.person_id, bench, ttl=-5))
        assert got.status_code == 404 and got.json()["code"] == "not_found"


def test_a_picture_link_and_a_file_link_are_no_page_token(db_url: str) -> None:
    with rig(db_url) as r:
        r.new_bench()
        assert page(r, picture_token(r.w.alana.household_id)).status_code == 404
        from ashley.files import links as file_links
        token = file_links.mint(KEY, file_links.Grant(r.w.alana.household_id, "ab" * 32, "image/png", True, int(time.time()) + 100)).url.rsplit("/", 1)[-1]
        assert page(r, token).status_code == 404


def test_a_bench_that_is_gone_is_404(db_url: str) -> None:
    with rig(db_url) as r:
        got = page(r, page_token(r.w.alana.household_id, r.w.alana.person_id, 987_654))
        assert got.status_code == 404 and got.json()["code"] == "not_found"


def test_a_piece_that_is_gone_is_404(db_url: str) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        r.add_note(bench)
        got = page(r, page_token(r.w.alana.household_id, r.w.alana.person_id, bench, 987_654))
        assert got.status_code == 404 and got.json()["code"] == "not_found"


def test_a_token_for_a_person_who_does_not_own_the_bench_is_404(db_url: str) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        got = page(r, page_token(r.w.sam.household_id, r.w.sam.person_id, bench))
        assert got.status_code == 404


def test_a_token_naming_another_household_never_reads_the_bench(db_url: str) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        r.add_note(bench, "secret-title")
        for who in (r.w.zed,):
            got = page(r, page_token(who.household_id, who.person_id, bench))
            assert got.status_code == 404 and "secret-title" not in got.text
        mixed = page(r, page_token(r.w.zed.household_id, r.w.alana.person_id, bench))
        assert mixed.status_code == 404 and "secret-title" not in mixed.text


def test_the_page_logs_ids_and_never_the_token(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    with rig(db_url) as r:
        bench = r.new_bench()
        piece = r.add_note(bench)
        token = page_token(r.w.alana.household_id, r.w.alana.person_id, bench, piece)
        with caplog.at_level(logging.DEBUG):
            assert page(r, token).status_code == 200
        (line,) = fields_of(caplog, "look.page")
        assert bench in line.values() and piece in line.values() and r.w.alana.household_id in line.values()
        assert token not in log_text(caplog) and token.split(".")[0] not in log_text(caplog)


def test_a_picture_link_serves_the_bytes_in_place(db_url: str) -> None:
    with rig(db_url) as r:
        hid = r.w.alana.household_id
        r.store.held[key_of(hid, sha(SHOT_BYTES))] = SHOT_BYTES
        got = picture(r, picture_token(hid))
        assert got.status_code == 200 and got.content == SHOT_BYTES
        assert got.headers["content-type"].split(";")[0] == "image/jpeg"
        assert "attachment" not in got.headers.get("content-disposition", "")


def test_a_picture_link_needs_no_session(db_url: str) -> None:
    with rig(db_url, signed_in=False) as r:
        r.store.held[key_of(r.w.alana.household_id, sha(SHOT_BYTES))] = SHOT_BYTES
        assert picture(r, picture_token(r.w.alana.household_id)).status_code == 200


@pytest.mark.parametrize("token", ["x", "a.b", "...."])
def test_a_malformed_picture_link_is_404(db_url: str, token: str) -> None:
    with rig(db_url) as r:
        got = picture(r, token)
        assert got.status_code == 404 and got.json()["code"] == "not_found"


def test_a_forged_or_expired_picture_link_is_404(db_url: str) -> None:
    with rig(db_url) as r:
        hid = r.w.alana.household_id
        r.store.held[key_of(hid, sha(SHOT_BYTES))] = SHOT_BYTES
        forged = links.mint_picture(b"z" * 40, links.Picture(hid, sha(SHOT_BYTES), "image/jpeg", int(time.time()) + 100))
        assert picture(r, forged).status_code == 404
        assert picture(r, picture_token(hid, ttl=-5)).status_code == 404


def test_a_page_token_and_a_file_link_are_no_picture_link(db_url: str) -> None:
    with rig(db_url) as r:
        hid = r.w.alana.household_id
        r.store.held[key_of(hid, sha(SHOT_BYTES))] = SHOT_BYTES
        assert picture(r, page_token(hid, r.w.alana.person_id, 1)).status_code == 404
        from ashley.files import links as file_links
        token = file_links.mint(KEY, file_links.Grant(hid, sha(SHOT_BYTES), "image/jpeg", True, int(time.time()) + 100)).url.rsplit("/", 1)[-1]
        assert picture(r, token).status_code == 404


def test_a_picture_whose_bytes_are_gone_is_404(db_url: str) -> None:
    with rig(db_url) as r:
        got = picture(r, picture_token(r.w.alana.household_id))
        assert got.status_code == 404 and got.json()["code"] == "not_found"


def test_bytes_kept_only_under_the_files_prefix_are_not_served_as_a_look(db_url: str) -> None:
    with rig(db_url) as r:
        from ashley.files.intake import key_of as file_key
        hid = r.w.alana.household_id
        r.store.held[file_key(hid, sha(SHOT_BYTES))] = SHOT_BYTES
        assert picture(r, picture_token(hid)).status_code == 404


def test_a_store_that_cannot_be_asked_is_503_unavailable(db_url: str) -> None:
    from bench_look_blind_support import FakeStore
    with rig(db_url, store=FakeStore(down=True)) as r:
        got = picture(r, picture_token(r.w.alana.household_id))
        assert got.status_code == 503 and got.json()["code"] == "unavailable"


def test_a_household_never_fetches_anothers_look(db_url: str) -> None:
    with rig(db_url) as r:
        alana, zed = r.w.alana.household_id, r.w.zed.household_id
        r.store.held[key_of(alana, sha(SHOT_BYTES))] = SHOT_BYTES
        got = picture(r, picture_token(zed))
        assert got.status_code == 404 and SHOT_BYTES not in got.content
        assert picture(r, picture_token(alana)).status_code == 200


def test_two_households_with_the_same_bytes_are_served_their_own(db_url: str) -> None:
    with rig(db_url) as r:
        alana, zed = r.w.alana.household_id, r.w.zed.household_id
        r.store.held[key_of(alana, sha(b"same"))] = b"alana-copy"
        r.store.held[key_of(zed, sha(b"same"))] = b"zed-copy"
        assert picture(r, picture_token(alana, b"same")).content == b"alana-copy"
        assert picture(r, picture_token(zed, b"same")).content == b"zed-copy"


def test_a_refused_page_is_not_cached_either(db_url: str) -> None:
    with rig(db_url) as r:
        got = page(r, "x.y")
        assert got.status_code == 404 and "no-store" in got.headers["cache-control"]

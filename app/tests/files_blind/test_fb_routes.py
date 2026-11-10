"""`POST /api/benches/{id}/files` and `GET /api/files/{token}` through the real app: statuses, what a piece carries
on the wire, the headers a file is served with, and that a link is the only credential."""

import logging
import time
from typing import Any
from urllib.parse import quote

import pytest
from ashley.api.bench_file_models import PieceFile
from ashley.files import links
from ashley.files.intake import key_of
from ashley.workshop import rules as workshop_rules
from httpx2 import Response
from files_blind_support import CONFIG, fields_of, log_text, Rig, GIF89, HTML, JPEG, LINK_KEY, PDF, PNG, TEXT, ZIP, FakeStore, rig, sha

KEY = LINK_KEY.encode()
MAX_PIECES = workshop_rules.load().max_pieces


def pieces(r: Rig, bench_id: int) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = r.bench(bench_id)["pieces"]
    return found


def fetch(r: Rig, url: str) -> Response:
    return r.client.get(url)


def test_an_upload_is_200_with_the_new_pieces_id_and_the_piece_is_on_the_bench(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        got = r.upload(b, PNG, "pic.png", "image/png")
        assert got.status_code == 200
        body = got.json()
        assert set(body) >= {"seq", "piece_id"}
        (piece,) = pieces(r, b)
        assert piece["id"] == body["piece_id"] and piece["kind"] == "image" and piece["title"] == "pic.png"


def test_the_piece_carries_its_file_on_the_wire(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        r.upload(b, PNG, "pic.png", "image/png")
        r.upload(b, PDF, "doc.pdf")
        img, doc = (PieceFile.model_validate(p["file"]) for p in pieces(r, b))
        assert (img.name, img.size_bytes, img.media_type, img.image) == ("pic.png", len(PNG), "image/png", True)
        assert (doc.name, doc.size_bytes, doc.media_type, doc.image) == ("doc.pdf", len(PDF), "application/pdf", False)
        assert img.url is not None and img.expires_at is not None
        assert img.url.startswith("/api/files/") and "pic" not in img.url and "png" not in img.url.split(".")[-1]
        now = time.time()
        assert now + CONFIG.link_ttl_s / 2 - 2 <= img.expires_at <= now + CONFIG.link_ttl_s + 2


def test_a_piece_that_is_not_a_file_has_no_file(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        r.client.post(f"/api/benches/{b}/commands", json={"type": "add", "kind": "note", "title": "n", "body": "x", "size": "small"})
        assert pieces(r, b)[0]["file"] is None


def test_a_bench_read_again_hands_out_the_same_address_while_the_window_lasts(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        r.upload(b, PNG, "pic.png")
        one, two = pieces(r, b)[0]["file"], pieces(r, b)[0]["file"]
        assert (one["url"] == two["url"]) == (one["expires_at"] == two["expires_at"])
        assert abs(one["expires_at"] - two["expires_at"]) in (0, CONFIG.link_ttl_s // 2)


def test_the_link_serves_the_bytes_with_the_sniffed_type_and_safe_headers(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        r.upload(b, PNG, "pic.png", "image/png")
        url = pieces(r, b)[0]["file"]["url"]
        got = fetch(r, url)
        assert got.status_code == 200 and got.content == PNG
        assert got.headers["content-type"].split(";")[0] == "image/png"
        assert got.headers["x-content-type-options"].lower() == "nosniff"
        assert "sandbox" in got.headers["content-security-policy"]
        assert not got.headers.get("content-disposition", "inline").startswith("attachment")


@pytest.mark.parametrize(("data", "name", "media"), [(PDF, "r.pdf", "application/pdf"), (ZIP, "z.zip", "application/zip"),
                                                      (TEXT, "t.txt", "text/plain")])
def test_a_file_that_is_not_an_image_is_an_attachment(db_url: str, data: bytes, name: str, media: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        r.upload(b, data, name)
        got = fetch(r, pieces(r, b)[0]["file"]["url"])
        assert got.status_code == 200 and got.content == data
        assert got.headers["content-type"].split(";")[0] == media
        assert got.headers["content-disposition"].startswith("attachment")
        assert got.headers["x-content-type-options"].lower() == "nosniff"


def test_html_uploaded_as_html_comes_back_as_plain_text_in_an_attachment(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        assert r.upload(b, HTML, "page.html", "text/html").status_code == 200
        piece = pieces(r, b)[0]
        assert piece["kind"] == "file" and piece["file"]["media_type"] == "text/plain"
        got = fetch(r, piece["file"]["url"])
        assert got.headers["content-type"].split(";")[0] == "text/plain" and got.headers["content-disposition"].startswith("attachment")


def test_a_percent_encoded_name_is_decoded_and_reduced_to_a_plain_file_name(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        r.upload(b, TEXT, quote("café menu.csv"), "text/csv")
        r.upload(b, TEXT, quote("../../etc/notes.txt", safe=""))
        names = [p["file"]["name"] for p in pieces(r, b)]
        assert names == ["café menu.csv", "notes.txt"]
        assert pieces(r, b)[0]["file"]["media_type"] == "text/csv"


def test_no_name_header_gives_a_name_all_the_same(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        got = r.client.post(f"/api/benches/{b}/files", content=TEXT, headers={"content-type": "application/octet-stream"})
        assert got.status_code == 200 and pieces(r, b)[0]["file"]["name"]


def test_the_same_bytes_twice_are_two_pieces_and_one_object_and_two_households_are_two_objects(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        r.upload(b, PNG, "a.png")
        r.upload(b, PNG, "b.png")
        assert len(pieces(r, b)) == 2 and len(r.store.held) == 1
        r.as_("zed")
        z = r.new_bench()
        r.upload(z, PNG, "a.png")
        assert len(r.store.held) == 2 and {k.rsplit("/", 1)[1] for k in r.store.held} == {sha(PNG)}
        assert len({k.split("/")[1] for k in r.store.held}) == 2
        assert key_of(r.w.alana.household_id, sha(PNG)) in r.store.held


def test_a_link_reaches_only_its_own_households_bytes(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        r.upload(b, PNG, "a.png")
        r.as_("zed")
        zb = r.new_bench()
        r.upload(zb, JPEG, "z.jpg")
        zurl = pieces(r, zb)[0]["file"]["url"]
        assert fetch(r, zurl).content == JPEG
        grant = links.Grant(r.w.zed.household_id, sha(PNG), "image/png", True, int(time.time()) + 100)
        assert fetch(r, links.mint(KEY, grant).url).status_code == 404


def test_an_upload_to_a_bench_that_is_not_yours_is_404_and_stores_nothing(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        r.as_("zed")
        got = r.upload(b, PNG, "a.png")
        assert got.status_code == 404 and got.json()["code"] == "not_found"
        assert all(k.startswith(f"bench/{r.w.zed.household_id}/") for k in r.store.held)
        r.as_("alana")
        assert not pieces(r, b)


def test_an_upload_to_a_closed_bench_is_410_closed(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        r.client.post(f"/api/benches/{b}/close")
        got = r.upload(b, PNG, "a.png")
        assert got.status_code == 410 and got.json()["code"] == "closed"
        assert not pieces(r, b)


def test_an_upload_to_a_full_bench_is_409_a_refused_command(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        for i in range(MAX_PIECES):
            r.client.post(f"/api/benches/{b}/commands", json={"type": "add", "kind": "note", "title": str(i), "body": "", "size": "small"})
        got = r.upload(b, PNG, "a.png")
        assert got.status_code == 409 and got.json()["reason"] == "full"
        assert len(pieces(r, b)) == MAX_PIECES


def test_an_empty_upload_is_422_refused(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        got = r.upload(b, b"", "a.txt")
        assert got.status_code == 422 and got.json()["code"] == "refused"
        assert r.store.held == {}


@pytest.mark.parametrize(("data", "declared"), [(b"\x00\x01\x02\x03", ""), (PNG, "application/pdf"), (TEXT, "image/png"), (b"abc\x00", "text/plain")])
def test_content_the_config_does_not_allow_or_that_is_not_what_it_says_is_415_unsupported(db_url: str, data: bytes, declared: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        got = r.upload(b, data, "a", declared)
        assert got.status_code == 415 and got.json()["code"] == "unsupported"
        assert r.store.held == {} and not pieces(r, b)


def test_a_body_of_exactly_the_limit_is_taken(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        data = b"PK\x03\x04" + bytes(CONFIG.max_bytes - 4)
        got = r.upload(b, data, "big.zip")
        assert got.status_code == 200 and len(pieces(r, b)) == 1


def test_a_person_uploads_as_themselves(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        r.upload(b, PNG, "a.png")
        assert r.bench(b)["pieces"][0]["changed_author"] == "person"
        assert r.bench(b)["pieces"][0]["changed_person_id"] == r.w.alana.person_id


def test_a_body_over_the_limit_is_413_too_large_and_nothing_is_kept(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        got = r.upload(b, b"PK\x03\x04" + bytes(CONFIG.max_bytes - 3), "big.zip")
        assert got.status_code == 413 and got.json()["code"] == "too_large"
        assert r.store.held == {} and not pieces(r, b)


def test_a_store_that_cannot_be_reached_is_503_unavailable_and_nothing_is_added(db_url: str) -> None:
    with rig(db_url, FakeStore(down=True)) as r:
        b = r.new_bench()
        got = r.upload(b, PNG, "a.png")
        assert got.status_code == 503 and got.json()["code"] == "unavailable"
        assert not pieces(r, b)


def test_signed_out_is_401_and_nothing_is_kept(db_url: str) -> None:
    with rig(db_url, signed_in=False) as r:
        got = r.upload(1, PNG, "a.png")
        assert got.status_code == 401
        assert r.store.held == {}


def test_a_json_body_is_not_an_upload_a_cross_site_form_could_send(db_url: str) -> None:
    with rig(db_url, signed_in=False) as r:
        got = r.upload(1, PNG, "a.png", content_type="application/json")
        assert got.status_code in (401, 403) and r.store.held == {}


def test_a_large_piece_cannot_be_added_by_the_commands_route_with_a_body_the_caller_wrote(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        r.upload(b, PDF, "d.pdf")
        body = pieces(r, b)[0]["body"]
        for kind in ("file", "image"):
            got = r.client.post(f"/api/benches/{b}/commands", json={"type": "add", "kind": kind, "title": "x", "body": body, "size": "small"})
            assert got.status_code != 200
        assert len(pieces(r, b)) == 1


def test_a_large_pieces_body_cannot_be_edited_but_its_title_can(db_url: str) -> None:
    with rig(db_url) as r:
        b = r.new_bench()
        r.upload(b, PDF, "d.pdf")
        piece = pieces(r, b)[0]
        edit = {"type": "edit", "piece_id": piece["id"], "base_version": piece["piece_version"]}
        bad = r.client.post(f"/api/benches/{b}/commands", json={**edit, "title": "t", "body": "{}"})
        assert bad.status_code == 409 and bad.json()["reason"] == "bad_file"
        ok = r.client.post(f"/api/benches/{b}/commands", json={**edit, "title": "renamed", "body": piece["body"]})
        assert ok.status_code == 200 and pieces(r, b)[0]["title"] == "renamed"


# --- GET /api/files/{token} -----------------------------------------------------------------------------------------


def grant_for(r: Rig, data: bytes, media: str = "application/pdf", inline: bool = False, ttl: int = 100, key: bytes = KEY, put: bool = True) -> str:
    h = r.w.alana.household_id
    if put:
        r.store.held[key_of(h, sha(data))] = data
    return links.mint(key, links.Grant(h, sha(data), media, inline, int(time.time()) + ttl)).url


def test_a_valid_link_serves_with_no_session_at_all(db_url: str) -> None:
    with rig(db_url, signed_in=False) as r:
        got = fetch(r, grant_for(r, PDF))
        assert got.status_code == 200 and got.content == PDF
        assert got.headers["content-type"].split(";")[0] == "application/pdf"
        assert got.headers["content-disposition"].startswith("attachment")


def test_a_served_file_is_cached_by_the_browser_alone_and_no_longer_than_its_link_lives(db_url: str) -> None:
    with rig(db_url) as r:
        control = fetch(r, grant_for(r, PDF, ttl=100)).headers["cache-control"].lower()
        assert "private" in control and "public" not in control
        age = int(control.split("max-age=")[1].split(",")[0])
        assert 0 < age <= 100


def test_a_link_shows_in_place_only_when_its_token_says_so(db_url: str) -> None:
    with rig(db_url) as r:
        shown = fetch(r, grant_for(r, GIF89, "image/gif", inline=True))
        saved = fetch(r, grant_for(r, GIF89, "image/gif", inline=False))
        assert not shown.headers.get("content-disposition", "inline").startswith("attachment")
        assert saved.headers["content-disposition"].startswith("attachment")


def forged(url: str) -> str:
    """`url` with one signature character changed. Not the last one: its spare bits can decode to the same bytes."""
    i = len(url) - 5
    return url[:i] + ("B" if url[i] == "A" else "A") + url[i + 1:]


@pytest.mark.parametrize("mutate", ["forged", "expired", "other_key", "malformed", "empty_object"])
def test_a_link_that_is_forged_expired_foreign_or_malformed_is_404_not_found(db_url: str, mutate: str) -> None:
    with rig(db_url) as r:
        url = {"forged": lambda: forged(grant_for(r, PDF)), "expired": lambda: grant_for(r, PDF, ttl=-30),
               "other_key": lambda: grant_for(r, PDF, key=b"x" * 40), "malformed": lambda: "/api/files/not-a-token",
               "empty_object": lambda: grant_for(r, b"never stored", put=False)}[mutate]()
        got = fetch(r, url)
        assert got.status_code == 404 and got.json()["code"] == "not_found"
        assert b"%PDF" not in got.content


def test_a_link_when_no_store_can_be_asked_is_503(db_url: str) -> None:
    with rig(db_url) as r:
        url = grant_for(r, PDF)
        r.store.down = True
        got = fetch(r, url)
        assert got.status_code == 503 and got.json()["code"] == "unavailable"


def test_the_names_and_tokens_stay_out_of_the_logs(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        with rig(db_url) as r:
            b = r.new_bench()
            r.upload(b, PDF, quote("zebra-private-name.pdf"))
            url = pieces(r, b)[0]["file"]["url"]
            fetch(r, url)
    token = url.rsplit("/", 1)[1]
    text = log_text(caplog)
    assert "zebra-private-name" not in text and token not in text
    (served,) = fields_of(caplog, "files.served")
    assert served["household"] is not None and served["size"] == len(PDF)

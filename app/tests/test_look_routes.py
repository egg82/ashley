"""`GET /api/look/{token}` through the real app over a real database: a valid token is its bench as its owner sees it,
or one piece of it; a forged, expired, other-purpose or missing-key token, a bench of another person, or a gone piece is
404; an unreachable workshop is 503; nothing is cached and the log never holds the token."""

import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import pytest
from ashley import services
from ashley.api.person import person_signed_in
from ashley.files import links as file_links
from ashley.files.intake import key_of as file_key
from ashley.files.memory import MemoryStore
from ashley.files.store import ObjectStore
from ashley.looks import links
from ashley.looks.keys import key_of as look_key
from ashley.main import create_app
from ashley.people.model import Person
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person
from fastapi.testclient import TestClient

PUBLIC = "https://ashley.test"
KEY = "k" * 40


class Rig:
    def __init__(self, client: TestClient, home: int, owner: int, other: int, bench: int, pieces: list[int]) -> None:
        self.client, self.home, self.owner, self.other = client, home, owner, other
        self.bench, self.pieces = bench, pieces

    def token(self, piece: int | None = None, who: int | None = None, bench: int | None = None, ttl: int = 100,
              key: str = KEY, home: int | None = None) -> str:
        grant = links.Grant(home or self.home, who or self.owner, bench or self.bench, piece, int(time.time()) + ttl)
        return links.mint(key.encode(), grant)

    def get(self, token: str) -> Any:
        return self.client.get(f"/api/look/{token}")


@contextmanager
def rig(url: str) -> Generator[Rig]:
    home = household(url)
    owner, other = person(url, home, "owner"), person(url, home, "other")
    app = create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC, files_endpoints="http://nas.test:1",
                              files_bucket="b", files_access_key="a", files_secret_key="s", files_link_key=KEY))
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, Person(owner, home, "Owner"))
    client = TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC})
    with client:
        bench = int(client.post("/api/benches", json={"title": "shed"}).json()["id"])
        pieces: list[int] = []
        for title in ("one", "two"):
            added = client.post(f"/api/benches/{bench}/commands", json={
                "type": "add", "kind": "note", "title": title, "body": "body", "size": "small"})
            pieces.append(int(added.json()["piece_id"]))
        yield Rig(client, home, owner, other, bench, pieces)


def test_a_valid_token_is_the_whole_bench_as_its_owner_sees_it_and_is_not_cached(db_url: str) -> None:
    with rig(db_url) as r:
        got = r.get(r.token())
        assert got.status_code == 200 and got.headers["cache-control"] == "no-store"
        body = got.json()
        assert [p["id"] for p in body["view"]["pieces"]] == r.pieces and body["view"]["bench"]["id"] == r.bench
        assert "note" in [k["name"] for k in body["rules"]["kinds"]]


def test_a_token_naming_a_piece_is_that_piece_alone(db_url: str) -> None:
    with rig(db_url) as r:
        body = r.get(r.token(piece=r.pieces[1])).json()
        shown = body["view"]
        assert [p["id"] for p in shown["pieces"]] == [r.pieces[1]] and shown["shelf"] == [] and shown["recent"] == []


@pytest.mark.parametrize("bad", ["x", "a.b", "e30.e30"])
def test_a_malformed_token_is_404(db_url: str, bad: str) -> None:
    with rig(db_url) as r:
        got = r.get(bad)
        assert got.status_code == 404 and got.json()["code"] == "not_found"


def test_a_forged_expired_or_other_purpose_token_is_404(db_url: str) -> None:
    with rig(db_url) as r:
        assert r.get(r.token(key="z" * 40)).status_code == 404
        assert r.get(r.token(ttl=-1)).status_code == 404
        file_token = file_links.mint(KEY.encode(), file_links.Grant(r.home, "a" * 64, "image/png", True,
                                                                   int(time.time()) + 100)).url.rsplit("/", 1)[1]
        assert r.get(file_token).status_code == 404


def test_a_bench_of_another_person_or_household_or_a_gone_piece_is_404(db_url: str) -> None:
    with rig(db_url) as r:
        assert r.get(r.token(who=r.other)).status_code == 404
        assert r.get(r.token(home=r.home + 1000)).status_code == 404
        assert r.get(r.token(bench=r.bench + 1000)).status_code == 404
        assert r.get(r.token(piece=999)).status_code == 404


def test_an_unreachable_workshop_is_503(db_url: str) -> None:
    with rig(db_url) as r:
        token = r.token()
        services.unregister(Workshop)
        got = r.get(token)
        assert got.status_code == 503 and got.json()["code"] == "unavailable"


def test_the_log_names_ids_and_never_the_token(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    with rig(db_url) as r:
        token = r.token(piece=r.pieces[0])
        r.get(token)
    text = "\n".join(f"{x.getMessage()} {getattr(x, 'fields', {})}" for x in caplog.records)
    assert "look.page" in text and token not in text and token.split(".")[0] not in text


def picture_token(r: Rig, sha: str = "c" * 64, ttl: int = 100, key: str = KEY) -> str:
    return links.mint_picture(key.encode(), links.Picture(r.home, sha, "image/jpeg", int(time.time()) + ttl))


def test_a_picture_link_serves_the_bytes_in_place_from_the_looks_prefix_only(db_url: str) -> None:
    with rig(db_url) as r:
        sha = "c" * 64
        store = MemoryStore()
        store.objects[look_key(r.home, sha)] = b"\xff\xd8\xff-bytes"
        store.objects[file_key(r.home, "d" * 64)] = b"a file, not a look"
        services.register(ObjectStore, store)
        got = r.client.get(links.PICTURE_PATH + picture_token(r, sha))
        assert got.status_code == 200 and got.content == b"\xff\xd8\xff-bytes"
        assert got.headers["content-type"] == "image/jpeg" and got.headers["content-disposition"] == "inline"
        assert got.headers["x-content-type-options"] == "nosniff"
        assert r.client.get(links.PICTURE_PATH + picture_token(r, "d" * 64)).status_code == 404


def test_a_bad_expired_or_page_token_serves_no_picture_and_a_down_store_is_503(db_url: str) -> None:
    with rig(db_url) as r:
        store = MemoryStore()
        store.objects[look_key(r.home, "c" * 64)] = b"x"
        services.register(ObjectStore, store)
        for token in (picture_token(r, key="z" * 40), picture_token(r, ttl=-1), r.token(), "x", ""):
            assert r.client.get(links.PICTURE_PATH + token).status_code == 404
        store.down = True
        assert r.client.get(links.PICTURE_PATH + picture_token(r)).status_code == 503

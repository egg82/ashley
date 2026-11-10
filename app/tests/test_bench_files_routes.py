"""Uploads and downloads through the real app over a real database, the object store in memory: a file is uploaded as
the request body and appears as an image or file piece with a short-lived link; the link serves the bytes as the type
they were judged to be (never as a page of this site) until it ends; the bytes are judged by content, not by the type
the client said; refusals leave nothing on the bench; another household's link, another person's bench and a closed
bench reach nothing; logs name no file."""

import asyncio
import dataclasses
import time
from collections.abc import AsyncGenerator, Generator

import pytest
from files_support import CSV, ELF, HTML, PDF, PNG
from ashley import services
from ashley.api import bench_files, person
from ashley.api.bench_file_models import PieceFile
from ashley.api.models import ErrorResponse
from ashley.api.person import person_signed_in, person_uploading
from ashley.api.workshop_models import BenchDetail, CommandApplied, CommandRefused
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.files import links
from ashley.files.intake import key_of
from ashley.files.memory import MemoryStore
from ashley.files.store import ObjectStore
from ashley.inference.inference import Inference
from ashley.main import create_app
from ashley.people.model import Person
from ashley.people.people import People
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from ashley.workshop import bench_file, stored_file
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi import FastAPI
from fastapi.testclient import TestClient
from respond_support import ALANA, SAM, Fakes, wired as wired
from starlette.requests import Request
from test_workshop_routes import PUBLIC, command, opened, seeded

LINK_KEY = "l" * 40
OCTET = {"content-type": "application/octet-stream"}


class Box:
    """One app over the test database with an in-memory object store, signed in as whoever `__call__` names last."""

    def __init__(self, app: FastAPI, client: TestClient, store: MemoryStore) -> None:
        self.app = app
        self.client = client
        self.store = store

    def __call__(self, who: Person) -> TestClient:
        for dependency in (person_signed_in, person_uploading):
            self.app.dependency_overrides[dependency] = lambda: SignedIn(1, who)
        return self.client


@pytest.fixture
def box(db_url: str, wired: Fakes) -> Generator[Box]:
    seeded(db_url)
    settings = Settings(database_url=db_url, build_version="test", public_url=PUBLIC, files_endpoints="http://nas.invalid",
                        files_bucket="ashley", files_access_key="k", files_secret_key="s", files_link_key=LINK_KEY)
    app = create_app(settings)
    with TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}) as client:
        services.register(People, wired.people)
        services.register(Conversations, wired.conversations)
        services.register(InFlight, InFlight.null())
        services.register(Inference, wired.inference)
        store = MemoryStore()
        services.register(ObjectStore, store)
        yield Box(app, client, store)
    services.unregister(Workshop)
    services.unregister(ObjectStore)


def upload(client: TestClient, bench: int, data: bytes, name: str = "thing.bin", said: str = "") -> tuple[int, dict[str, object]]:
    headers = {**OCTET, "x-file-name": name, **({"x-file-type": said} if said else {})}
    response = client.post(f"/api/benches/{bench}/files", content=data, headers=headers)
    return response.status_code, response.json()


def detail(client: TestClient, bench: int) -> BenchDetail:
    return BenchDetail.model_validate(client.get(f"/api/benches/{bench}").json())


def file_of(client: TestClient, bench: int, piece: int) -> PieceFile:
    found = next(p for p in detail(client, bench).pieces if p.id == piece)
    assert found.file is not None
    return found.file


def test_an_uploaded_image_is_an_image_piece_with_a_link_that_serves_its_bytes_in_place(box: Box) -> None:
    client = box(ALANA)
    bench = opened(client)
    status, body = upload(client, bench.id, PNG, "cat.png", "image/png")
    assert status == 200
    applied = CommandApplied.model_validate(body)
    got = detail(client, bench.id)
    (piece,) = got.pieces
    assert (piece.id, piece.kind, piece.title, piece.changed_author) == (applied.piece_id, "image", "cat.png", "person")
    assert piece.placement.size == "medium"
    assert piece.file is not None
    assert (piece.file.name, piece.file.size_bytes, piece.file.media_type, piece.file.image) == ("cat.png", len(PNG), "image/png", True)
    assert piece.file.url is not None and piece.file.expires_at is not None
    served = client.get(piece.file.url, headers={"cookie": ""})
    assert served.status_code == 200 and served.content == PNG
    assert served.headers["content-type"] == "image/png" and served.headers["content-disposition"] == "inline"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in served.headers["content-security-policy"]
    assert list(box.store.objects.values()) == [PNG]
    stored = stored_file.file_of(piece.body)
    assert stored is not None and list(box.store.objects) == [key_of(ALANA.household_id, stored.sha256)]


def test_a_pdf_is_a_file_piece_served_as_a_download(box: Box) -> None:
    client = box(ALANA)
    bench = opened(client)
    status, body = upload(client, bench.id, PDF, "plan.pdf")
    assert status == 200
    file = file_of(client, bench.id, CommandApplied.model_validate(body).piece_id or 0)
    assert (file.media_type, file.image) == ("application/pdf", False) and file.url is not None
    served = client.get(file.url)
    assert served.content == PDF and served.headers["content-disposition"] == "attachment"
    assert detail(client, bench.id).pieces[0].kind == "file" and detail(client, bench.id).pieces[0].placement.size == "small"


def test_markup_uploaded_is_text_and_downloads_as_text_never_as_a_page(box: Box) -> None:
    client = box(ALANA)
    bench = opened(client)
    status, body = upload(client, bench.id, HTML, "page.html", "text/html")
    assert status == 200
    file = file_of(client, bench.id, CommandApplied.model_validate(body).piece_id or 0)
    assert file.media_type == "text/plain" and file.url is not None
    served = client.get(file.url)
    assert served.headers["content-type"].startswith("text/plain") and served.headers["content-disposition"] == "attachment"


def test_a_text_type_the_client_names_is_kept(box: Box) -> None:
    client = box(ALANA)
    bench = opened(client)
    status, body = upload(client, bench.id, CSV, "a.csv", "text/csv")
    assert status == 200
    assert file_of(client, bench.id, CommandApplied.model_validate(body).piece_id or 0).media_type == "text/csv"


def test_what_is_refused_is_refused_before_anything_is_stored_or_added(box: Box, monkeypatch: pytest.MonkeyPatch) -> None:
    client = box(ALANA)
    bench = opened(client)
    cases = [(b"", "empty.txt", "", 422, "refused"), (ELF, "a.out", "", 415, "unsupported"),
             (CSV, "a.png", "image/png", 415, "unsupported"), (PNG, "a.pdf", "application/pdf", 415, "unsupported"),
             (b"\xff\xfe\x00", "a.txt", "text/plain", 415, "unsupported")]
    for data, name, said, status, code in cases:
        got, body = upload(client, bench.id, data, name, said)
        assert (got, ErrorResponse.model_validate(body).code) == (status, code), name
    monkeypatch.setattr(bench_file, "CONFIG", dataclasses.replace(bench_file.CONFIG, max_bytes=len(PNG) - 1))
    got, body = upload(client, bench.id, PNG, "big.png")
    assert (got, ErrorResponse.model_validate(body).code) == (413, "too_large")
    assert box.store.objects == {} and detail(client, bench.id).pieces == []


def test_the_size_limit_is_enforced_on_a_body_that_does_not_say_how_long_it_is(box: Box, monkeypatch: pytest.MonkeyPatch) -> None:
    client = box(ALANA)
    bench = opened(client)
    monkeypatch.setattr(bench_file, "CONFIG", dataclasses.replace(bench_file.CONFIG, max_bytes=10))
    response = client.post(f"/api/benches/{bench.id}/files", content=(chunk for chunk in (CSV, CSV, CSV)),
                           headers={**OCTET, "x-file-name": "c.csv"})
    assert response.status_code == 413 and box.store.objects == {}


def test_an_upload_to_a_full_bench_is_refused_with_the_benchs_reason(box: Box, monkeypatch: pytest.MonkeyPatch) -> None:
    client = box(ALANA)
    bench = opened(client)
    for n in range(50):
        assert command(client, bench.id, {"type": "add", "kind": "note", "title": str(n), "body": "", "size": "small"})[0] == 200
    status, body = upload(client, bench.id, CSV, "late.csv")
    assert status == 409 and CommandRefused.model_validate(body).reason == "full"


def test_another_persons_bench_and_a_closed_bench_take_no_upload(box: Box) -> None:
    bench = opened(box(ALANA))
    assert upload(box(SAM), bench.id, CSV, "a.csv")[0] == 404
    assert box(ALANA).post(f"/api/benches/{bench.id}/close").status_code == 200
    status, body = upload(box(ALANA), bench.id, CSV, "a.csv")
    assert status == 410 and ErrorResponse.model_validate(body).code == "closed"
    assert upload(box(ALANA), 99999, CSV, "a.csv")[0] == 404


def test_a_page_cannot_make_an_image_or_file_piece_by_writing_its_body(box: Box) -> None:
    client = box(ALANA)
    bench = opened(client)
    _, up = upload(client, bench.id, PDF, "plan.pdf")
    piece = CommandApplied.model_validate(up).piece_id or 0
    body = detail(client, bench.id).pieces[0].body
    status, refused = command(client, bench.id, {"type": "add", "kind": "file", "title": "forged", "body": body, "size": "small"})
    assert status == 422 and refused["code"] == "refused"
    status, refused = command(client, bench.id, {"type": "edit", "piece_id": piece, "base_version": 1, "title": "plan.pdf", "body": "{}"})
    assert status == 409 and refused["reason"] == "bad_file"
    status, _ = command(client, bench.id, {"type": "edit", "piece_id": piece, "base_version": 1, "title": "renamed", "body": body})
    assert status == 200 and detail(client, bench.id).pieces[0].title == "renamed"


def test_undoing_the_upload_takes_the_piece_off_and_leaves_the_bytes_for_a_redo(box: Box) -> None:
    client = box(ALANA)
    bench = opened(client)
    _, up = upload(client, bench.id, PDF, "plan.pdf")
    assert command(client, bench.id, {"type": "undo", "seq": CommandApplied.model_validate(up).seq})[0] == 200
    assert detail(client, bench.id).pieces == [] and len(box.store.objects) == 1


def test_a_link_stops_working_when_it_ends_and_a_bench_read_hands_out_a_fresh_one(box: Box) -> None:
    client = box(ALANA)
    bench = opened(client)
    _, up = upload(client, bench.id, PDF, "plan.pdf")
    piece = CommandApplied.model_validate(up).piece_id or 0
    first = file_of(client, bench.id, piece)
    ttl = bench_file.CONFIG.link_ttl_s
    assert first.expires_at is not None and first.url is not None
    assert time.time() + ttl // 2 < first.expires_at <= time.time() + ttl
    assert file_of(client, bench.id, piece).url == first.url
    grant = links.check(LINK_KEY.encode(), first.url[len(links.PATH):], time.time())
    assert grant is not None
    ended = links.mint(LINK_KEY.encode(), dataclasses.replace(grant, expires_at=int(time.time()) - 1))
    gone = client.get(ended.url)
    assert gone.status_code == 404 and ErrorResponse.model_validate(gone.json()).code == "not_found"
    assert client.get(first.url).status_code == 200


def test_forged_links_and_another_households_hash_reach_nothing(box: Box) -> None:
    client = box(ALANA)
    bench = opened(client)
    _, up = upload(client, bench.id, PDF, "plan.pdf")
    url = file_of(client, bench.id, CommandApplied.model_validate(up).piece_id or 0).url or ""
    grant = links.check(LINK_KEY.encode(), url[len(links.PATH):], time.time())
    assert grant is not None
    foreign = links.mint(LINK_KEY.encode(), dataclasses.replace(grant, household_id=grant.household_id + 1))
    assert client.get(foreign.url).status_code == 404
    other_key = links.mint(b"x" * 40, grant)
    assert client.get(other_key.url).status_code == 404
    assert client.get(url[:-2] + "xx").status_code == 404
    assert client.get(f"{links.PATH}nonsense").status_code == 404


def test_a_store_that_cannot_be_reached_is_unavailable_and_changes_nothing(box: Box) -> None:
    client = box(ALANA)
    bench = opened(client)
    _, up = upload(client, bench.id, PDF, "plan.pdf")
    url = file_of(client, bench.id, CommandApplied.model_validate(up).piece_id or 0).url or ""
    box.store.down = True
    assert client.get(url).status_code == 503
    status, body = upload(client, bench.id, CSV, "a.csv")
    assert status == 503 and ErrorResponse.model_validate(body).code == "unavailable"
    box.store.down = False
    assert len(detail(client, bench.id).pieces) == 1


def test_a_file_that_is_gone_from_every_store_is_not_found(box: Box) -> None:
    client = box(ALANA)
    bench = opened(client)
    _, up = upload(client, bench.id, PDF, "plan.pdf")
    url = file_of(client, bench.id, CommandApplied.model_validate(up).piece_id or 0).url or ""
    box.store.objects.clear()
    assert client.get(url).status_code == 404


def test_the_logs_carry_sizes_and_types_but_no_file_name_and_no_content(box: Box, capsys: pytest.CaptureFixture[str]) -> None:
    client = box(ALANA)
    bench = opened(client)
    capsys.readouterr()
    status, body = upload(client, bench.id, PDF + b"SECRET-CONTENT", "secret-plans.pdf")
    assert status == 200
    url = file_of(client, bench.id, CommandApplied.model_validate(body).piece_id or 0).url or ""
    client.get(url)
    text = capsys.readouterr().out
    assert "files.stored" in text and "files.served" in text and "application/pdf" in text
    for leaked in ("secret-plans", "SECRET-CONTENT", url[len(links.PATH):]):
        assert leaked not in text


def test_a_body_that_says_it_is_too_long_is_not_read_at_all() -> None:
    class Unread(Request):
        async def stream(self) -> AsyncGenerator[bytes]:
            raise AssertionError("the body was read")
            yield b""

    request = Unread({"type": "http", "method": "POST", "headers": [(b"content-length", b"1000")]})
    assert asyncio.run(bench_files.read_body(request, 999)) is None


def _request(content_type: str | None, origin: str = PUBLIC) -> Request:
    headers = [(b"origin", origin.encode()), (b"content-length", b"3")]
    if content_type is not None:
        headers.append((b"content-type", content_type.encode()))

    class App:
        class state:
            class settings:
                public_url = PUBLIC

    return Request({"type": "http", "method": "POST", "headers": headers, "app": App})


def test_an_upload_must_come_from_this_site_as_raw_bytes_which_a_form_cannot_send() -> None:
    assert person.same_site(_request("application/octet-stream"), person.BYTES)
    for refused in ("multipart/form-data; boundary=x", "text/plain", "application/x-www-form-urlencoded", "application/json", None):
        assert not person.same_site(_request(refused), person.BYTES), refused
    assert not person.same_site(_request("application/octet-stream", "https://evil.example"), person.BYTES)
    assert not person.same_site(_request("application/octet-stream"), person.JSON)

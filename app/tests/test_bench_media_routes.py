"""Video and audio files through the real app: an upload is a `clip` or `audio` piece whose link is served in place, to
a player that seeks by byte range; a type that is neither (an HEIC image shares a video container's signature) is
refused."""

import pytest
from files_support import HEIC, MP3, MP4, WEBM
from ashley.api.models import ErrorResponse
from ashley.api.workshop_models import CommandApplied
from fastapi.testclient import TestClient
from respond_support import ALANA
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from respond_support import wired as wired
from test_bench_files_routes import Box, box as box, detail, upload
from test_workshop_routes import opened

BIG = MP4 + bytes(range(256)) * 8


def served(client: TestClient, bench: int, data: bytes, name: str, said: str = "") -> tuple[str, str, str]:
    """The kind, size and link of the piece an upload of `data` made."""
    status, body = upload(client, bench, data, name, said)
    assert status == 200
    piece = CommandApplied.model_validate(body).piece_id or 0
    found = next(p for p in detail(client, bench).pieces if p.id == piece)
    assert found.file is not None and found.file.url is not None
    return found.kind, found.placement.size, found.file.url


@pytest.mark.parametrize("data,name,said,kind,size", [(BIG, "a.mp4", "video/mp4", "clip", "medium"),
                                                      (WEBM, "a.webm", "", "clip", "medium"),
                                                      (MP3, "a.mp3", "audio/mpeg", "audio", "medium")],
                         ids=["mp4", "webm", "mp3"])
def test_a_video_or_audio_upload_is_the_piece_that_plays_it_and_is_served_in_place(
        box: Box, data: bytes, name: str, said: str, kind: str, size: str) -> None:
    client = box(ALANA)
    bench = opened(client)
    got_kind, got_size, url = served(client, bench.id, data, name, said)
    assert (got_kind, got_size) == (kind, size)
    response = client.get(url, headers={"cookie": ""})
    assert response.status_code == 200 and response.content == data
    assert response.headers["content-disposition"] == "inline" and response.headers["accept-ranges"] == "bytes"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_a_range_is_served_as_the_bytes_asked_and_one_outside_the_file_is_refused(box: Box) -> None:
    client = box(ALANA)
    url = served(client, opened(client).id, BIG, "a.mp4")[2]
    part = client.get(url, headers={"range": "bytes=10-19"})
    assert part.status_code == 206 and part.content == BIG[10:20]
    assert part.headers["content-range"] == f"bytes 10-19/{len(BIG)}" and part.headers["content-type"] == "video/mp4"
    tail = client.get(url, headers={"range": "bytes=-5"})
    assert tail.status_code == 206 and tail.content == BIG[-5:]
    beyond = client.get(url, headers={"range": f"bytes={len(BIG)}-"})
    assert beyond.status_code == 416 and beyond.headers["content-range"] == f"bytes */{len(BIG)}"
    assert ErrorResponse.model_validate(beyond.json()).code == "refused"


def test_an_image_in_a_video_container_is_not_taken(box: Box) -> None:
    client = box(ALANA)
    bench = opened(client)
    assert upload(client, bench.id, HEIC, "a.heic")[0] == 415 and detail(client, bench.id).pieces == []

"""Site and video pieces on the wire, through the real app over a real database: the kinds are served `live` with
their format; a video piece reads back with `video` (provider, the url as written, the privacy embed url, start) and
every other piece with null; a body outside the kind's shape is refused 409 `bad_site` or `bad_video`."""

import json

from ashley.api.workshop_models import BenchDetail, CommandRefused, WorkshopKinds
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from respond_support import ALANA, wired as wired
from test_workshop_routes import As, command, opened
from test_workshop_routes import signed_in as signed_in

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
VIDEO = {"type": "add", "kind": "video", "title": "talk", "body": json.dumps({"url": URL, "start": 42}), "size": "large"}
SITE = {"type": "add", "kind": "site", "title": "graphs", "body": "https://en.wikipedia.org/wiki/Graph_theory",
        "size": "full"}


def read(client: TestClient, bench: int) -> BenchDetail:
    return BenchDetail.model_validate(client.get(f"/api/benches/{bench}").json())


def test_the_site_and_video_kinds_are_served_live(signed_in: As) -> None:
    got = WorkshopKinds.model_validate(signed_in(ALANA).get("/api/workshop/kinds").json())
    by_name = {k.name: k for k in got.kinds}
    assert (by_name["site"].family, by_name["site"].format) == ("live", "site")
    assert (by_name["video"].family, by_name["video"].format) == ("live", "video")


def test_a_video_piece_reads_back_with_its_embed_and_start(signed_in: As) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    assert command(client, bench, VIDEO)[0] == 200 and command(client, bench, SITE)[0] == 200
    video, site = read(client, bench).pieces
    assert video.video is not None
    assert (video.video.provider, video.video.url, video.video.start) == ("youtube", URL, 42)
    assert video.video.embed_url == "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?start=42"
    assert site.video is None and site.body == SITE["body"]


def test_an_empty_video_piece_has_no_video_yet(signed_in: As) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    command(client, bench, {**VIDEO, "body": ""})
    assert read(client, bench).pieces[0].video is None


def test_a_body_outside_the_kinds_shape_is_refused(signed_in: As) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    for sent, reason in (({**SITE, "body": "http://a.example/"}, "bad_site"), ({**VIDEO, "body": URL}, "bad_video")):
        status, got = command(client, bench, sent)
        assert status == 409 and CommandRefused.model_validate(got).reason == reason

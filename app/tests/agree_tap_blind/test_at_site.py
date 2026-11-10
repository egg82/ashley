"""The tap is a cookie-signed write, so it is the person route rule (`api.person`): from this site, as JSON, by a live
session. A cross-site or signed-out tap runs nothing and consumes nothing."""

import pytest
from agree_tap_blind_support import (AGREE_PATH, OK, PUBLIC, UNPROCESSABLE, World, agree_body, world)


def untouched(w: World, pid: int) -> None:
    w.settle()
    assert w.tools.ran == [] and w.model.calls == 0 and w.work_rows() == 0 and w.pending(w.alana)
    assert w.tap(w.alana, pid).status_code == OK, "control: the same tap from this site is taken"


def test_a_cross_site_post_is_forbidden_and_runs_nothing(db_url: str) -> None:
    with world(db_url) as w:
        pid = w.hold(w.alana)
        assert w.tap(w.alana, pid, headers={"origin": "https://evil.example"}).status_code == 403
        untouched(w, pid)


def test_a_post_marked_cross_site_with_no_origin_is_forbidden(db_url: str) -> None:
    with world(db_url) as w:
        pid = w.hold(w.alana)
        assert w.tap(w.alana, pid, headers={"sec-fetch-site": "cross-site"}).status_code == 403
        untouched(w, pid)


@pytest.mark.parametrize("content_type", ["application/x-www-form-urlencoded", "text/plain"])
def test_a_body_a_form_can_send_is_forbidden(db_url: str, content_type: str) -> None:
    with world(db_url) as w:
        pid = w.hold(w.alana)
        w.client.cookies.set("__Host-ashley_session", w.alana.token, domain="ashley.test")
        got = w.client.post(AGREE_PATH, content=f"proposal_id={pid}",
                            headers={"origin": PUBLIC, "content-type": content_type})
        assert got.status_code == 403
        untouched(w, pid)


def test_a_signed_out_tap_is_unauthorized_and_runs_nothing(db_url: str) -> None:
    with world(db_url) as w:
        pid = w.hold(w.alana)
        assert w.tap(None, pid).status_code == 401
        untouched(w, pid)


def test_the_body_cannot_name_another_person_to_agree_as(db_url: str) -> None:
    with world(db_url) as w:
        pid = w.hold(w.alana)
        body = {**agree_body(pid), "person_id": w.alana.id, "speaker_id": w.alana.id, "text": "yes do it"}
        got = w.tap(w.sam, pid, body=body)
        assert got.status_code == UNPROCESSABLE
        w.settle()
        assert w.tools.ran == [] and w.pending(w.alana)

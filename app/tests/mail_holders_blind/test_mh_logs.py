"""A move and a share each leave a log line of ids; no line carries an address, a name, a label, a secret or a ref."""

import pytest
from fastapi.testclient import TestClient
from mail_holders_blind_support import (BOTH, Boxes, People, all_logs, as_, hand, lines, log_text, make, share)

REF, NAME, LABEL, SECRET = "alana.private@home.test", "Alana's private inbox", "my-private-label", "log-secret-0042"


def quiet_boxes(boxes: Boxes) -> None:
    boxes.refs = [REF]
    boxes.names = {REF: NAME}


def test_a_move_logs_the_connection_and_the_holder(client: TestClient, boxes: Boxes, caplog: pytest.LogCaptureFixture) -> None:
    cid = make(client)
    all_logs(caplog)
    hand(client, cid, "household")
    hand(client, cid, "person")
    moved = lines(caplog, "connections.moved")
    assert [(m["connection"], m["holder"]) for m in moved] == [(cid, "household"), (cid, "person")]


def test_a_share_logs_the_connection_and_whether_shared(client: TestClient, boxes: Boxes,
                                                        caplog: pytest.LogCaptureFixture) -> None:
    cid = make(client)
    all_logs(caplog)
    share(client, cid, "alana@home.test")
    share(client, cid, "alana@home.test", False)
    shared = lines(caplog, "connections.resource_shared")
    assert [(s["connection"], s["shared"]) for s in shared] == [(cid, True), (cid, False)]


def test_a_refused_move_or_share_logs_neither_line(client: TestClient, people: People,
                                                   caplog: pytest.LogCaptureFixture) -> None:
    cid = make(client)
    as_(client, people, "sam")
    all_logs(caplog)
    hand(client, cid, "household")
    share(client, cid, "alana@home.test")
    assert lines(caplog, "connections.moved") == [] and lines(caplog, "connections.resource_shared") == []


def test_a_move_the_service_refuses_logs_no_moved_line(client: TestClient, people: People,
                                                       caplog: pytest.LogCaptureFixture) -> None:
    cid = make(client)
    assert hand(client, cid, "household").status_code == 200
    as_(client, people, "sam")
    all_logs(caplog)
    caplog.clear()
    assert hand(client, cid, "person").status_code == 403
    assert lines(caplog, "connections.moved") == []


def test_no_line_carries_a_ref_a_name_a_label_or_a_secret(client: TestClient, boxes: Boxes,
                                                          caplog: pytest.LogCaptureFixture) -> None:
    quiet_boxes(boxes)
    all_logs(caplog)
    cid = make(client, BOTH, LABEL, SECRET)
    share(client, cid, REF)
    client.get("/api/connections")
    hand(client, cid, "household")
    hand(client, cid, "person")
    text = log_text(caplog)
    assert "connections.moved" in text and "connections.resource_shared" in text
    leaked = [v for v in (REF, NAME, LABEL, SECRET, "https://music.test", "music.test") if v in text]
    assert not leaked, leaked

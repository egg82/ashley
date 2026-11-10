"""One logfmt line per call, and nothing sensitive in any of them."""

import hashlib
import re

from herdr_bridge_blind_support import LABEL_MARK, PERSON, PROMPT_MARK, SID, Bridge

OTHER = "intruder-person-77"
GUESS = "guessed-token-abc123"


def fields(line: str) -> dict[str, str]:
    return dict(re.findall(r"(\w+)=(\"[^\"]*\"|\S*)", line))


def traffic(b: Bridge) -> list[str]:
    """Every kind of call, accepted and refused, with identifying text in all of them."""
    idle = b.add("alpha", "idle")
    busy = b.add("bravo", "working")
    sub = b.mkdir("secretdirname")
    b.get("/v1/whoami")
    b.get("/v1/sessions")
    b.get(f"/v1/sessions/{idle.session_id}/read", lines="5")
    b.post(f"/v1/sessions/{idle.session_id}/prompt", {"text": PROMPT_MARK})
    b.post(f"/v1/sessions/{busy.session_id}/prompt", {"text": PROMPT_MARK})
    b.post(f"/v1/sessions/{SID}/prompt", {"text": PROMPT_MARK})
    b.start(sub, LABEL_MARK, model="haiku")
    b.start(b.outside, LABEL_MARK)
    b.start(f"{b.root}/nonexistent-{PROMPT_MARK}", LABEL_MARK)
    b.start(sub, "Bad Label " + LABEL_MARK)
    b.get("/v1/whoami", token=GUESS)
    b.get("/v1/whoami", person=OTHER)
    b.post(f"/v1/sessions/{idle.session_id}/close")
    b.get(f"/v1/sessions/{SID}/read")
    b.call("POST", f"/v1/sessions/{idle.session_id}/prompt", raw=b"{" + PROMPT_MARK.encode())
    return b.log.lines


def test_no_line_carries_text_paths_labels_the_token_or_the_person(bridge: Bridge) -> None:
    lines = traffic(bridge)
    assert lines
    blob = "\n".join(lines)
    ids = [a.session_id for a in bridge.herdr.agents]
    for secret in (PROMPT_MARK, LABEL_MARK, bridge.token, GUESS, PERSON, OTHER, "SCREEN-MARKER", "secretdirname",
                   str(bridge.root), str(bridge.outside), "nonexistent", bridge.root.name, "alpha", "bravo", "haiku", SID,
                   *ids):
        assert secret not in blob, secret
    assert "w1:p" not in blob


def test_each_call_leaves_exactly_one_line(bridge: Bridge) -> None:
    bridge.get("/v1/whoami")
    assert len(bridge.log.lines) == 1
    bridge.get("/v1/sessions")
    assert len(bridge.log.lines) == 2
    bridge.get("/v1/whoami", token="nope")
    assert len(bridge.log.lines) == 3
    assert all("\n" not in line for line in bridge.log.lines)


def test_a_line_is_key_value_pairs_with_call_status_ms_and_bytes(bridge: Bridge) -> None:
    bridge.get("/v1/sessions")
    f = fields(bridge.log.lines[0])
    for key in ("call", "status", "ms", "bytes"):
        assert key in f, bridge.log.lines[0]
    assert f["status"] == "200"
    assert f["ms"].isdigit() and f["bytes"].isdigit()
    assert "error" not in f
    assert re.fullmatch(r"(\w+=\S+ ?)+", bridge.log.lines[0].strip()), bridge.log.lines[0]


def test_a_refusal_names_its_error_code(bridge: Bridge) -> None:
    bridge.get("/v1/whoami")
    bridge.get("/v1/whoami", token="nope")
    bridge.get("/v1/whoami", person="intruder")
    bridge.start(bridge.outside, "abc")
    codes = [fields(line).get("error") for line in bridge.log.lines]
    assert codes == [None, "bad_token", "wrong_person", "dir_not_allowed"]


def test_a_line_about_a_session_carries_the_first_eight_hex_digits_of_its_sha256(bridge: Bridge) -> None:
    a = bridge.add("alpha")
    bridge.get(f"/v1/sessions/{a.session_id}/read")
    f = fields(bridge.log.lines[-1])
    assert f["session"] == hashlib.sha256(a.session_id.encode()).hexdigest()[:8]


def test_a_refused_call_about_an_unknown_session_still_logs_only_the_hash(bridge: Bridge) -> None:
    bridge.post(f"/v1/sessions/{SID}/close")
    f = fields(bridge.log.lines[-1])
    assert f.get("error") == "not_found"
    assert SID not in bridge.log.text()


def test_a_start_logs_no_session_id_in_clear_even_after_it_succeeds(bridge: Bridge) -> None:
    r = bridge.start(bridge.mkdir("p"), "abc")
    assert str(r.body["id"]) not in bridge.log.text()


def test_the_failure_a_start_swallows_is_still_logged_without_its_particulars(bridge: Bridge) -> None:
    bridge.herdr.never_reports = True
    bridge.start(bridge.mkdir("secretdirname"), LABEL_MARK)
    blob = bridge.log.text()
    assert bridge.log.lines
    assert fields(bridge.log.lines[-1]).get("error") == "unconfirmed"
    assert "secretdirname" not in blob and LABEL_MARK not in blob
    assert [str(t) for t in bridge.herdr.tabs] == []


def test_a_herdr_failure_logs_the_code_not_herdrs_words(bridge: Bridge) -> None:
    bridge.herdr.fail[("agent", "list")] = "weird_internal /home/x/y"
    bridge.get("/v1/sessions")
    assert fields(bridge.log.lines[-1]).get("error") == "herdr_unavailable"
    assert "/home/x/y" not in bridge.log.text()


def test_the_log_holds_up_when_the_screen_and_the_prompt_are_huge(bridge: Bridge) -> None:
    a = bridge.add("alpha")
    bridge.herdr.screen = ("SCREEN-MARKER " * 5000) + "\n"
    bridge.get(f"/v1/sessions/{a.session_id}/read", lines="400")
    bridge.post(f"/v1/sessions/{a.session_id}/prompt", {"text": PROMPT_MARK * 700})
    assert all(len(line) < 400 for line in bridge.log.lines)
    assert "SCREEN-MARKER" not in bridge.log.text()


def test_the_bytes_field_grows_with_the_answer(bridge: Bridge) -> None:
    bridge.get("/v1/sessions")
    for i in range(5):
        bridge.add(f"agent{i}")
    bridge.get("/v1/sessions")
    small, big = (int(fields(line)["bytes"]) for line in bridge.log.lines)
    assert 0 < small < big

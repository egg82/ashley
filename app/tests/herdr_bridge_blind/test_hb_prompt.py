"""Sending a prompt: size bounds, refusals by state, and text that is never an option."""

import json

import pytest
from herdr_bridge_blind_fake import FakeAgent
from herdr_bridge_blind_support import SID, Bridge


def prompt(b: Bridge, a: FakeAgent, text: object) -> tuple[int, dict[str, object]]:
    r = b.post(f"/v1/sessions/{a.session_id}/prompt", {"text": text})
    return r.status, r.body


def sent(b: Bridge) -> list[tuple[str, ...]]:
    return b.herdr.commands("agent", "prompt")


def test_an_idle_session_takes_a_prompt(bridge: Bridge) -> None:
    a = bridge.add("alpha", "idle")
    assert prompt(bridge, a, "hello there") == (200, {"submitted": True})
    [cmd] = sent(bridge)
    assert "hello there" in cmd
    assert any(w in (a.pane_id, a.name, a.session_id) for w in cmd)


def test_a_done_session_takes_a_prompt(bridge: Bridge) -> None:
    a = bridge.add("alpha", "done")
    assert prompt(bridge, a, "next")[0] == 200


def test_the_prompt_goes_to_the_named_session_only(bridge: Bridge) -> None:
    a, b = bridge.add("alpha"), bridge.add("bravo")
    prompt(bridge, b, "to bravo")
    [cmd] = sent(bridge)
    assert not any(w in (a.pane_id, a.name, a.session_id) for w in cmd)


@pytest.mark.parametrize("status,code", [("working", "busy"), ("blocked", "blocked"), ("unknown", "unknown_state")])
def test_a_session_not_ready_refuses_and_nothing_is_sent(bridge: Bridge, status: str, code: str) -> None:
    a = bridge.add("alpha", status)
    assert prompt(bridge, a, "hi") == (409, {"error": code})
    assert bridge.herdr.changes() == []


def test_a_status_herdr_invents_is_not_ready(bridge: Bridge) -> None:
    a = bridge.add("alpha", "levitating")
    assert prompt(bridge, a, "hi") == (409, {"error": "unknown_state"})
    assert sent(bridge) == []


@pytest.mark.parametrize("n", [1, 2, 7999, 8000])
def test_text_of_1_to_8000_characters_is_accepted(bridge: Bridge, n: int) -> None:
    a = bridge.add("alpha")
    assert prompt(bridge, a, "x" * n) == (200, {"submitted": True})


@pytest.mark.parametrize("n", [8001, 8002, 20000])
def test_longer_text_is_a_bad_request_and_nothing_is_sent(bridge: Bridge, n: int) -> None:
    a = bridge.add("alpha")
    assert prompt(bridge, a, "x" * n) == (400, {"error": "bad_request"})
    assert sent(bridge) == []


def utf8_post(b: Bridge, a: FakeAgent, text: str) -> int:
    raw = json.dumps({"text": text}, ensure_ascii=False).encode()
    return b.call("POST", f"/v1/sessions/{a.session_id}/prompt", raw=raw).status


def test_the_bound_counts_characters_not_bytes(bridge: Bridge) -> None:
    a = bridge.add("alpha")
    assert utf8_post(bridge, a, "é" * 8000) == 200
    assert utf8_post(bridge, a, "é" * 8001) == 400
    assert utf8_post(bridge, a, "\U0001f600" * 8000) == 200
    assert utf8_post(bridge, a, "\U0001f600" * 8001) == 400


def test_eight_thousand_non_ascii_characters_in_escaped_json_are_accepted(bridge: Bridge) -> None:
    a = bridge.add("alpha")
    assert prompt(bridge, a, "é" * 8000) == (200, {"submitted": True})


@pytest.mark.parametrize("text", ["", None, 5, ["a"], {"a": 1}, True, 1.5])
def test_text_that_is_empty_or_not_a_string_is_a_bad_request(bridge: Bridge, text: object) -> None:
    a = bridge.add("alpha")
    assert prompt(bridge, a, text) == (400, {"error": "bad_request"})
    assert sent(bridge) == []


@pytest.mark.parametrize(
    "raw",
    [b"", b"not json", b"[]", b'"text"', b"null", b"{}", b'{"txt": "hi"}', b'{"text": "hi"', b"\xff\xfe", b"123"],
)
def test_a_malformed_body_is_a_bad_request(bridge: Bridge, raw: bytes) -> None:
    a = bridge.add("alpha")
    r = bridge.call("POST", f"/v1/sessions/{a.session_id}/prompt", raw=raw)
    assert (r.status, r.body) == (400, {"error": "bad_request"})
    assert sent(bridge) == []


def test_a_huge_body_is_refused_unread_by_herdr(bridge: Bridge) -> None:
    a = bridge.add("alpha")
    r = bridge.call("POST", f"/v1/sessions/{a.session_id}/prompt", raw=b'{"text": "' + b"x" * 2_000_000 + b'"}')
    assert 400 <= r.status < 500
    assert sent(bridge) == []


def test_whitespace_only_text_is_still_text_or_a_bad_request_but_never_a_server_error(bridge: Bridge) -> None:
    a = bridge.add("alpha")
    assert prompt(bridge, a, "   \n  ")[0] in (200, 400)


@pytest.mark.parametrize(
    "text",
    ["-", "--", "-h", "--help", "--version", "-rf /", "--dangerously-skip-permissions", "-x\nsecond", "--text=boo", "---"],
)
def test_text_starting_with_a_dash_reaches_herdr_as_text_never_as_an_option(bridge: Bridge, text: str) -> None:
    a = bridge.add("alpha")
    assert prompt(bridge, a, text) == (200, {"submitted": True})
    [cmd] = sent(bridge)
    assert cmd[-1] == text and cmd.count(text) == 1, cmd
    assert cmd[-2] == a.pane_id and cmd.count("--") == (1 if text == "--" else 0), cmd


@pytest.mark.parametrize("text", ["a; rm -rf /", "$(id)", "`id`", "a && b", "'quoted'", '"dq"', "line1\nline2", "\x00nul"])
def test_shell_metacharacters_are_just_text(bridge: Bridge, text: str) -> None:
    a = bridge.add("alpha")
    assert prompt(bridge, a, text)[0] in (200, 400)
    for cmd in sent(bridge):
        assert text in cmd
        assert cmd[0] != "sh" and "-c" not in cmd


def test_the_text_is_one_argument_whatever_it_holds(bridge: Bridge) -> None:
    a = bridge.add("alpha")
    text = "two words and --a-flag inside"
    prompt(bridge, a, text)
    [cmd] = sent(bridge)
    assert text in cmd


def test_an_unknown_session_is_not_found_and_nothing_is_sent(bridge: Bridge) -> None:
    bridge.add("alpha")
    r = bridge.post(f"/v1/sessions/{SID}/prompt", {"text": "hi"})
    assert (r.status, r.body) == (404, {"error": "not_found"})
    assert bridge.herdr.changes() == []


def test_the_session_is_checked_before_the_body(bridge: Bridge) -> None:
    r = bridge.post(f"/v1/sessions/{SID}/prompt", {"text": ""})
    assert r.status in (400, 404)
    assert bridge.herdr.changes() == []


def test_a_timeout_after_sending_is_unconfirmed(bridge: Bridge) -> None:
    a = bridge.add("alpha")
    bridge.herdr.fail[("agent", "prompt")] = "timeout"
    assert prompt(bridge, a, "hi") == (504, {"error": "unconfirmed"})


def test_herdr_missing_when_prompting_is_herdr_unavailable(bridge: Bridge) -> None:
    a = bridge.add("alpha")
    bridge.herdr.fail[("agent", "list")] = "missing"
    assert prompt(bridge, a, "hi") == (503, {"error": "herdr_unavailable"})
    assert sent(bridge) == []


def test_a_refusal_never_echoes_the_prompt(bridge: Bridge) -> None:
    a = bridge.add("alpha", "working")
    r = bridge.post(f"/v1/sessions/{a.session_id}/prompt", {"text": "SECRET-ECHO"})
    assert "SECRET-ECHO" not in json.dumps(r.body)


def test_extra_fields_beside_text_are_a_bad_request_and_send_no_keys(bridge: Bridge) -> None:
    a = bridge.add("alpha")
    for extra in ({"keys": "Enter"}, {"submit": True}, {"cmd": "id"}):
        r = bridge.post(f"/v1/sessions/{a.session_id}/prompt", {"text": "hi", **extra})
        assert (r.status, r.body) == (400, {"error": "bad_request"})
    assert sent(bridge) == []


def test_herdr_saying_the_agent_is_blocked_or_gone_is_blocked_or_not_found(bridge: Bridge) -> None:
    a = bridge.add("alpha")
    bridge.herdr.fail[("agent", "prompt")] = "agent_blocked"
    assert prompt(bridge, a, "hi") == (409, {"error": "blocked"})
    bridge.herdr.fail[("agent", "prompt")] = "agent_not_found"
    assert prompt(bridge, a, "hi") == (404, {"error": "not_found"})


@pytest.mark.parametrize("text", ["x" * 8000, "  padded  ", "tail\n", "\ttab"])
def test_the_text_reaches_herdr_exactly_as_sent(bridge: Bridge, text: str) -> None:
    a = bridge.add("alpha")
    assert prompt(bridge, a, text) == (200, {"submitted": True})
    [cmd] = sent(bridge)
    assert text in cmd

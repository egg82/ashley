"""Starting a session: label and model patterns, a taken label, and a start that never comes up."""

import pytest
from herdr_bridge_blind_support import Bridge


def made(b: Bridge) -> list[tuple[str, ...]]:
    return b.herdr.commands("tab", "create")


@pytest.mark.parametrize("label", ["a", "abc", "a1", "a_b-c", "a" * 32, "z0_-9"])
def test_a_label_is_a_lowercase_letter_then_up_to_31_of_a_z_0_9_underscore_dash(bridge: Bridge, label: str) -> None:
    r = bridge.start(bridge.mkdir("p"), label)
    assert r.status in (200, 201)
    assert r.body["label"] == label


@pytest.mark.parametrize(
    "label",
    ["", "A", "Abc", "aBc", "1abc", "-abc", "_abc", "a" * 33, "a b", "a\n", "abc\n", "\nabc", "a.b", "a/b", "../x",
     "a;b", "$(x)", "--flag", "-rf", "é", "aé", "a\x00", " a", "a "],
)
def test_any_other_label_is_a_bad_request_and_creates_nothing(bridge: Bridge, label: str) -> None:
    r = bridge.start(bridge.mkdir("p"), label)
    assert (r.status, r.body) == (400, {"error": "bad_request"})
    assert bridge.herdr.changes() == []


@pytest.mark.parametrize("label", [None, 5, ["abc"], {"a": "b"}, True])
def test_a_label_that_is_not_a_string_is_a_bad_request(bridge: Bridge, label: object) -> None:
    r = bridge.start(bridge.mkdir("p"), label)
    assert (r.status, r.body) == (400, {"error": "bad_request"})
    assert bridge.herdr.changes() == []


def test_a_request_with_no_label_is_a_bad_request(bridge: Bridge) -> None:
    r = bridge.post("/v1/sessions", {"dir": str(bridge.mkdir("p"))})
    assert (r.status, r.body) == (400, {"error": "bad_request"})
    assert bridge.herdr.changes() == []


@pytest.mark.parametrize("raw", [b"", b"nope", b"[]", b"null", b'"x"', b"{"])
def test_a_malformed_start_body_is_a_bad_request(bridge: Bridge, raw: bytes) -> None:
    r = bridge.call("POST", "/v1/sessions", raw=raw)
    assert (r.status, r.body) == (400, {"error": "bad_request"})
    assert bridge.herdr.changes() == []


@pytest.mark.parametrize("model", ["haiku", "opus", "claude-sonnet-4-5", "opus[1m]", "a", "A1.2_b-c", "m" * 64])
def test_a_model_name_is_passed_to_herdr_as_one_argument(bridge: Bridge, model: str) -> None:
    r = bridge.start(bridge.mkdir("p"), "abc", model=model)
    assert r.status in (200, 201)
    [cmd] = bridge.herdr.commands("agent", "start")
    assert model in cmd or any(a.endswith("=" + model) for a in cmd)


def test_without_a_model_none_is_passed(bridge: Bridge) -> None:
    bridge.start(bridge.mkdir("p"), "abc")
    [cmd] = bridge.herdr.commands("agent", "start")
    assert "--model" not in cmd and not any(a.startswith("--model=") for a in cmd)


@pytest.mark.parametrize(
    "model",
    ["", "-x", "--dangerously-skip-permissions", "--model", "a b", "a;b", "$(id)", "`id`", "a\n", "haiku\n", "m" * 65,
     "-", "[x]", ".x", "_x", "a/b", "a\x00", "é", "a&b", "a|b", "a>b", "a'b", 'a"b', "a\\b"],
)
def test_any_other_model_is_a_bad_request_and_creates_nothing(bridge: Bridge, model: str) -> None:
    r = bridge.start(bridge.mkdir("p"), "abc", model=model)
    assert (r.status, r.body) == (400, {"error": "bad_request"})
    assert bridge.herdr.changes() == []


@pytest.mark.parametrize("model", [5, ["haiku"], {"a": 1}, True])
def test_a_model_that_is_not_a_string_is_a_bad_request(bridge: Bridge, model: object) -> None:
    r = bridge.start(bridge.mkdir("p"), "abc", model=model)
    assert (r.status, r.body) == (400, {"error": "bad_request"})
    assert bridge.herdr.changes() == []


def test_a_label_a_live_agent_already_has_is_label_taken_and_nothing_is_created(bridge: Bridge) -> None:
    bridge.add("taken")
    r = bridge.start(bridge.mkdir("p"), "taken")
    assert (r.status, r.body) == (409, {"error": "label_taken"})
    assert bridge.herdr.changes() == []


def test_a_label_is_free_again_once_its_session_is_closed(bridge: Bridge) -> None:
    first = bridge.start(bridge.mkdir("p"), "again")
    bridge.post(f"/v1/sessions/{first.body['id']}/close")
    assert bridge.start(bridge.mkdir("p"), "again").status in (200, 201)


def test_a_start_that_never_reports_a_state_is_unconfirmed_and_its_tab_is_closed(bridge: Bridge) -> None:
    bridge.herdr.never_reports = True
    r = bridge.start(bridge.mkdir("p"), "ghost")
    assert (r.status, r.body) == (504, {"error": "unconfirmed"})
    assert len(made(bridge)) == 1
    assert bridge.herdr.tabs == {}
    assert bridge.herdr.agents == []
    assert len(bridge.herdr.closed) == 1


def test_a_start_herdr_gives_up_on_is_unconfirmed_and_its_tab_is_closed(bridge: Bridge) -> None:
    bridge.herdr.fail[("agent", "start")] = "timeout"
    r = bridge.start(bridge.mkdir("p"), "ghost")
    assert (r.status, r.body) == (504, {"error": "unconfirmed"})
    assert bridge.herdr.tabs == {}


def test_herdr_missing_during_a_start_leaves_no_tab(bridge: Bridge) -> None:
    bridge.herdr.fail[("agent", "start")] = "missing"
    r = bridge.start(bridge.mkdir("p"), "ghost")
    assert r.status in (503, 504)
    assert bridge.herdr.tabs == {}


def test_a_start_herdr_refuses_leaves_no_tab_behind(bridge: Bridge) -> None:
    bridge.herdr.fail[("agent", "start")] = "pane_busy"
    r = bridge.start(bridge.mkdir("p"), "ghost")
    assert r.body in ({"error": "herdr_unavailable"}, {"error": "unconfirmed"})
    assert bridge.herdr.tabs == {}


def test_a_tab_that_will_not_be_made_is_herdr_unavailable_and_starts_no_agent(bridge: Bridge) -> None:
    bridge.herdr.fail[("tab", "create")] = "no_workspace"
    r = bridge.start(bridge.mkdir("p"), "ghost")
    assert (r.status, r.body) == (503, {"error": "herdr_unavailable"})
    assert bridge.herdr.commands("agent", "start") == []


def test_a_start_that_reports_a_state_only_after_a_few_polls_succeeds_and_keeps_its_tab(bridge: Bridge) -> None:
    bridge.herdr.unknown_polls = 2
    r = bridge.start(bridge.mkdir("p"), "slowpoke")
    assert r.status in (200, 201)
    assert r.body["status"] != "unknown"
    assert len(bridge.herdr.tabs) == 1
    assert bridge.herdr.closed == []


def test_an_unconfirmed_start_leaves_other_sessions_alone(bridge: Bridge) -> None:
    keep = bridge.add("keeper")
    bridge.herdr.never_reports = True
    bridge.start(bridge.mkdir("p"), "ghost")
    assert [a.session_id for a in bridge.herdr.agents] == [keep.session_id]
    assert keep.tab_id in bridge.herdr.tabs


def test_a_failed_start_for_a_refused_directory_creates_no_tab(bridge: Bridge) -> None:
    r = bridge.start(bridge.outside, "abc")
    assert r.status == 403
    assert made(bridge) == []


@pytest.mark.parametrize("extra", [{"cmd": "id"}, {"argv": ["sh"]}, {"keys": "Enter"}, {"prompt": "hi"}, {"Dir": "/etc"}])
def test_a_start_with_fields_beyond_dir_label_and_model_is_a_bad_request(bridge: Bridge, extra: dict[str, object]) -> None:
    r = bridge.post("/v1/sessions", {"dir": str(bridge.mkdir("p")), "label": "abc", **extra})
    assert (r.status, r.body) == (400, {"error": "bad_request"})
    assert bridge.herdr.changes() == []


def test_the_session_started_is_a_claude_agent_in_the_tab_just_made(bridge: Bridge) -> None:
    bridge.start(bridge.mkdir("p"), "abc")
    [cmd] = bridge.herdr.commands("agent", "start")
    assert "claude" in cmd
    assert not any(w in cmd for w in ("codex", "shell", "bash", "sh"))

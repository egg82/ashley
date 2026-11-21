"""`browser_snapshot` and `browser_act` over a scripted browser: offered only when one is wired; a snapshot taints the
turn and carries each element's ref, role and name; an action is validated before the browser hears of it (a public https
address, bounded text) and a refusal from the page is an error with a hint; nothing logged holds an address or a name
from the page; and the contract tells her she types no password or card number."""

import asyncio
import json
import logging

import pytest
from ashley import services
from ashley.inference.model import ToolCall, ToolResult
from ashley.looks.session import BrowserSessions, Who
from ashley.looks.config import load
from ashley.tools import browser_session
from ashley.tools.browser_session import ACT, SNAPSHOT, BrowserSessionTools
from browser_support import SEEN, ScriptedSessions

PUBLIC = "https://93.184.216.34/checkout"
WHO = Who(7, 70)


def call(name: str, **arguments: object) -> ToolResult:
    return asyncio.run(BrowserSessionTools(7, 70).call(ToolCall("c1", name, arguments)))


@pytest.fixture
def sessions() -> ScriptedSessions:
    wired = ScriptedSessions()
    services.register(BrowserSessions, wired)
    return wired


def test_nothing_is_offered_while_no_browser_is_wired() -> None:
    assert asyncio.run(BrowserSessionTools(7, 70).catalogue()).specs == ()
    refused = call(SNAPSHOT)
    assert refused.is_error and "no browser" in refused.content


def test_the_two_tools_are_offered_with_their_contract(sessions: ScriptedSessions) -> None:
    offered = asyncio.run(BrowserSessionTools(7, 70).catalogue())
    snapshot, act = offered.specs
    assert (snapshot.name, snapshot.reads, snapshot.outside) == ("browser_snapshot", True, True)
    assert (act.name, act.reads, act.outside) == ("browser_act", False, False)
    assert "passwords, one-time codes or card numbers" in act.description
    assert offered.instructions is not None and "Never type a password" in offered.instructions
    assert act.parameters["required"] == ["action"]
    config = load()
    assert f"{config.session_max_actions} actions" in act.description


def test_a_snapshot_is_outside_words_and_names_each_element_by_ref(sessions: ScriptedSessions) -> None:
    done = call(SNAPSHOT)
    assert not done.is_error and done.outside is True and sessions.asked == [WHO]
    body = json.loads(done.content)
    assert (body["url"], body["title"], body["cut"], body["seconds_left"], body["actions_left"]) == (
        SEEN.url, "Cart", True, 540, 55)
    assert body["elements"] == [
        {"ref": "e0", "role": "textbox", "name": "Email"},
        {"ref": "e1", "role": "textbox", "name": "Password", "secret": True},
        {"ref": "e2", "role": "combobox", "name": "Size", "options": ["S", "L"]},
        {"ref": "e3", "role": "button", "name": "Buy", "disabled": True, "checked": True}]


def test_a_snapshot_takes_no_arguments(sessions: ScriptedSessions) -> None:
    assert call(SNAPSHOT, url=PUBLIC).is_error and sessions.asked == []


def test_each_step_reaches_the_browser_as_asked(sessions: ScriptedSessions) -> None:
    for arguments in ({"action": "navigate", "url": PUBLIC}, {"action": "click", "ref": "e3"},
                      {"action": "type", "ref": "e0", "text": "a@b.example", "submit": True},
                      {"action": "select", "ref": "e2", "value": "L"}):
        done = call(ACT, **arguments)
        assert not done.is_error and done.taints(False) is False
        assert json.loads(done.content) == {"done": arguments["action"], "seconds_left": 500, "actions_left": 54}
    assert [(a.action, a.ref, a.text, a.value, a.url, a.submit) for a in sessions.acts] == [
        ("navigate", None, None, None, PUBLIC, False), ("click", "e3", None, None, None, False),
        ("type", "e0", "a@b.example", None, None, True), ("select", "e2", None, "L", None, False)]
    assert set(sessions.asked) == {WHO}


def test_end_closes_the_session_and_says_whether_there_was_one(sessions: ScriptedSessions) -> None:
    assert json.loads(call(ACT, action="end").content) == {"ended": True}
    sessions.there = False
    assert json.loads(call(ACT, action="end").content) == {"ended": False}
    assert sessions.ended == [WHO, WHO] and sessions.acts == []


@pytest.mark.parametrize("arguments", [
    {}, {"action": "hover", "ref": "e1"}, {"action": "navigate"}, {"action": "navigate", "url": "http://93.184.216.34/"},
    {"action": "navigate", "url": "https://10.0.0.5/admin"}, {"action": "navigate", "url": "https://localhost/"},
    {"action": "navigate", "url": "file:///etc/hosts"}, {"action": "click", "ref": 3},
    {"action": "type", "ref": "e0", "text": "x" * (load().type_chars + 1)}, {"action": "type", "text": 5},
    {"action": "click", "ref": "e0", "submit": "yes"}, {"action": "click", "ref": "e0", "x": 10, "y": 20}])
def test_a_step_that_is_malformed_or_names_a_private_address_never_reaches_the_browser(
        sessions: ScriptedSessions, arguments: dict[str, object]) -> None:
    done = call(ACT, **arguments)
    assert done.is_error and sessions.acts == [] and sessions.asked == []


@pytest.mark.parametrize("reason", sorted(browser_session.HINTS))
def test_a_refusal_is_an_error_with_a_hint_for_that_reason(sessions: ScriptedSessions, reason: str) -> None:
    sessions.fails = reason
    for done in (call(SNAPSHOT), call(ACT, action="click", ref="e0")):
        assert done.is_error and browser_session.HINTS[reason] in done.content


def test_a_reason_nobody_listed_reads_as_a_failure(sessions: ScriptedSessions) -> None:
    sessions.fails = "novel"
    assert browser_session.HINTS["failed"] in call(SNAPSHOT).content


def test_a_tool_that_is_not_hers_is_unknown(sessions: ScriptedSessions) -> None:
    assert call("browser_hover").is_error


def test_nothing_logged_holds_an_address_or_a_name_from_the_page(sessions: ScriptedSessions,
                                                                caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    call(SNAPSHOT)
    call(ACT, action="navigate", url=PUBLIC)
    call(ACT, action="type", ref="e0", text="hunter2-secret-text")
    logged = caplog.text
    assert "tools.call" in logged
    for forbidden in ("93.184.216.34", "shop.example", "Password", "Email", "hunter2"):
        assert forbidden not in logged

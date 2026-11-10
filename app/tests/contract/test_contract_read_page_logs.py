"""`read_page`'s log line (outcome, bytes, chars, duration; never a URL, host, query or page text, shown with planted
markers and a control), and the four new keys of `look_up.json` and its prompt file."""

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest
from ashley import logs
from ashley.tools import look_up as look_up_module
from ashley.tools import look_up_config
from ashley.tools.look_up_config import LookUpConfig, load, parse
from conversations_support import events
from read_page_contract_support import (CONFIG, Dns, Move, Net, Responder, Rig, calls, failing, finish, install_dns,
                                        page, read, read_number, redirect, web)

HOST_MARK = "zqhost4417"
PATH_MARK = "zqpath4417"
TEXT_MARK = "zqtext4417"
QUERY_MARK = "zqquery4417"
MARKS = [HOST_MARK, PATH_MARK, TEXT_MARK, QUERY_MARK]
URL = f"https://{HOST_MARK}.test/{PATH_MARK}/hours"
Plan = Callable[[Net], list[Move]]
LINE_FIELDS = {"tool", "outcome", "bytes", "chars", "duration_ms"}


@pytest.fixture(autouse=True)
def dns(monkeypatch: pytest.MonkeyPatch) -> Dns:
    return install_dns(monkeypatch)


def logged(capsys: pytest.CaptureFixture[str], net: Net, plan: Plan) -> tuple[list[dict[str, str]], str]:
    logs.setup()
    capsys.readouterr()
    out = Rig(net).look_up(plan(net))
    assert out.result.is_error is False, "control: the look-up itself works"
    text = capsys.readouterr().out
    return [e for e in events(text, "tools.call") if e.get("tool") == "read_page"], text


def plan_for(arguments_number: int | None = None) -> Plan:
    def plan(net: Net) -> list[Move]:
        take = read(0, 0) if arguments_number is None else read_number(arguments_number)
        return [calls(web(f"hours of {QUERY_MARK}")), calls(take), finish()]

    return plan


def net_for(responder: Responder) -> Net:
    return Net(pages={f"{HOST_MARK}.test": responder, f"{HOST_MARK}b.test": page(f"<p>{TEXT_MARK}</p>")},
               fallback=[URL, URL])


def test_an_ok_read_logs_outcome_bytes_chars_and_duration(capsys: pytest.CaptureFixture[str]) -> None:
    body = f"<p>{TEXT_MARK} open 9-5</p>"
    (line,), out = logged(capsys, net_for(page(body)), plan_for())
    assert LINE_FIELDS <= set(line) and line["outcome"] == "ok"
    assert line["bytes"] == str(len(body.encode())) and line["duration_ms"].isdigit()
    assert 0 < int(line["chars"]) <= len(body)
    for mark in MARKS:
        assert mark not in out, mark


@pytest.mark.parametrize(("name", "responder", "number", "outcome"), [
    ("refused_type", page(f"<p>{TEXT_MARK}</p>", ctype="application/pdf"), None, "refused"),
    ("refused_redirect", redirect(f"http://{HOST_MARK}b.test/{PATH_MARK}"), None, "refused"),
    ("unavailable_status", page(f"<p>{TEXT_MARK}</p>", 503), None, "unavailable"),
    ("unavailable_timeout", failing(httpx2.ReadTimeout(f"{HOST_MARK} {PATH_MARK}")), None, "unavailable"),
    ("unavailable_connect", failing(httpx2.ConnectError(f"{URL}")), None, "unavailable"),
    ("error_number", page(f"<p>{TEXT_MARK}</p>"), 99, "error"),
])
def test_every_outcome_is_logged_and_no_url_host_query_or_text_reaches_a_line(
        capsys: pytest.CaptureFixture[str], name: str, responder: Responder, number: int | None, outcome: str) -> None:
    (line,), out = logged(capsys, net_for(responder), plan_for(number))
    assert line["outcome"] == outcome and LINE_FIELDS <= set(line), name
    assert line["bytes"].isdigit() and line["chars"].isdigit() and line["duration_ms"].isdigit()
    assert not any(mark in out for mark in MARKS), name


def test_a_non_public_host_is_refused_and_logged_without_its_name(capsys: pytest.CaptureFixture[str],
                                                                  dns: Dns) -> None:
    dns.table[f"{HOST_MARK}.test"] = ["10.0.0.5"]
    (line,), out = logged(capsys, net_for(page(f"<p>{TEXT_MARK}</p>")), plan_for())
    assert line["outcome"] == "refused" and any(HOST_MARK in h for h in dns.asked), "control: the host was looked up"
    assert HOST_MARK not in out and PATH_MARK not in out and QUERY_MARK not in out and TEXT_MARK not in out


def test_the_markers_are_where_the_controls_expect_them() -> None:
    net = net_for(page(f"<p>{TEXT_MARK}</p>"))
    out = Rig(net).look_up(plan_for()(net))
    assert QUERY_MARK in net.queries[0] and net.hits[0].url.path.startswith(f"/{PATH_MARK}")
    assert TEXT_MARK in out.pages[0].content, "control: the text reaches the model, so only the logs are being tested"


# look_up.json and look_up.md

GOOD: dict[str, Any] = {"max_rounds": 3, "result_chars": 8000, "answer_chars": 500, "max_sources": 3,
                        "page_timeout_s": 6, "max_redirects": 3, "page_bytes": 1000000, "page_chars": 6000}
SHIPPED = Path(look_up_config.__file__).parent / "look_up.json"
NEW_KEYS = ["page_timeout_s", "max_redirects", "page_bytes", "page_chars"]


def test_the_shipped_file_has_the_four_new_keys_with_the_contracts_values() -> None:
    data = json.loads(SHIPPED.read_text())
    assert set(data) == set(GOOD) and {k: data[k] for k in NEW_KEYS} == {k: GOOD[k] for k in NEW_KEYS}
    assert {k: data[k] for k in ("max_rounds", "answer_chars", "max_sources")} == {
        "max_rounds": 3, "answer_chars": 500, "max_sources": 3}
    config = load()
    assert isinstance(config, LookUpConfig) and dataclasses.asdict(config) == data


def test_the_shipped_result_chars_does_not_cut_a_full_page() -> None:
    assert load().result_chars >= load().page_chars + 40, "the result is a JSON object around the page text"


def test_a_file_with_all_the_keys_parses() -> None:
    assert parse(GOOD) == dataclasses.replace(CONFIG, result_chars=8000)


@pytest.mark.parametrize("key", list(GOOD))
def test_a_missing_key_is_a_value_error(key: str) -> None:
    with pytest.raises(ValueError):
        parse({k: v for k, v in GOOD.items() if k != key})


def test_an_unknown_key_is_a_value_error() -> None:
    with pytest.raises(ValueError):
        parse({**GOOD, "page_pixels": 3})


@pytest.mark.parametrize("key", NEW_KEYS)
@pytest.mark.parametrize("bad", [0, -1])
def test_a_new_number_that_is_not_positive_is_a_value_error(key: str, bad: int) -> None:
    with pytest.raises(ValueError):
        parse({**GOOD, key: bad})


@pytest.mark.parametrize("key", ["max_redirects", "page_bytes", "page_chars"])
def test_a_new_count_that_is_not_an_integer_is_a_value_error(key: str) -> None:
    with pytest.raises(ValueError):
        parse({**GOOD, key: "9"})


def test_the_look_up_prompt_names_read_page() -> None:
    text = Path(look_up_module.__file__).with_name("look_up.md").read_text()
    assert "read_page" in text and "search_web" in text

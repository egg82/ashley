"""The ending log line, the fixed lines, the tunable, the route and the ledger that a turn ending after its held line
rests on."""

import json
from importlib import resources
from pathlib import Path

import psycopg
import pytest
from ashley.channels import ending, inflight_config, unsaid
from ashley.channels.inflight_config import CONFIG, FILE, Config, load
from ashley.inference.reply import Reply
from later_support import Logged


def test_record_writes_one_respond_ended_line_of_ids_only(capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    ending.record("refused", 42, "wrap_up")
    got = logged.events("respond.ended")
    assert len(got) == 1
    assert (got[0]["reason"], got[0]["conversation"], got[0]["recovery"]) == ("refused", "42", "wrap_up")
    assert len([ln for ln in logged.read().splitlines() if "respond.ended" in ln]) == 1


@pytest.mark.parametrize("recovery", ["wrap_up", "fixed_line", "kept", "told_and_kept", "failed_shown", "other_runner"])
def test_record_carries_each_recovery_as_given(capsys: pytest.CaptureFixture[str], recovery: str) -> None:
    logged = Logged(capsys)
    ending.record("gave_up", 1, recovery)
    assert [e["recovery"] for e in logged.events("respond.ended")] == [recovery]


def test_record_accepts_an_unknown_conversation(capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    ending.record("unstorable", None, "kept")
    got = logged.events("respond.ended")
    assert len(got) == 1 and got[0]["reason"] == "unstorable"


def test_the_fixed_line_is_the_one_in_unsaid_json_and_is_said_as_spoken_and_text() -> None:
    data = json.loads(resources.files("ashley.channels").joinpath("unsaid.json").read_text())
    assert unsaid.LINE == data["line"] and unsaid.UNREACHABLE == data["unreachable"]
    assert unsaid.fixed() == unsaid.Said(spoken=unsaid.LINE, text=unsaid.LINE)
    assert unsaid.unreachable() == unsaid.Said(spoken=unsaid.UNREACHABLE, text=unsaid.UNREACHABLE)
    assert isinstance(unsaid.fixed(), Reply)


def test_the_two_lines_differ_and_say_something() -> None:
    assert unsaid.LINE.strip() and unsaid.UNREACHABLE.strip()
    assert unsaid.LINE != unsaid.UNREACHABLE


def test_the_unreachable_line_is_not_empty_for_either_medium() -> None:
    reply = unsaid.unreachable()
    assert not unsaid.empty(reply, "text") and not unsaid.empty(reply, "spoken")


def test_the_unavailable_retry_is_a_tunable_of_two_minutes_by_default() -> None:
    assert CONFIG.unavailable_retry_s == 120.0
    assert load() == CONFIG
    assert Config(1.0, 1.0, 1, 1).unavailable_retry_s == 120.0


def test_inflight_json_refuses_a_missing_or_non_positive_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = json.loads(FILE.read_text())
    assert set(raw) == {"claim_s", "poll_s", "max_attempts", "batch", "unavailable_retry_s"}
    for bad in ({k: v for k, v in raw.items() if k != "unavailable_retry_s"}, {**raw, "unavailable_retry_s": 0},
                {**raw, "unavailable_retry_s": -5}, {**raw, "extra": 1}):
        path = tmp_path / "inflight.json"
        path.write_text(json.dumps(bad))
        monkeypatch.setattr(inflight_config, "FILE", path)
        with pytest.raises(ValueError):
            inflight_config.load()


def test_the_wrap_up_task_routes_to_providers_other_than_the_one_chat_leads_with() -> None:
    routes = json.loads(resources.files("ashley.inference").joinpath("routes.json").read_text())["tasks"]
    assert routes["wrap_up"]
    assert routes["wrap_up"][0]["provider"] != routes["chat"][0]["provider"]
    assert all(r["timeout_s"] > 0 for r in routes["wrap_up"])


def test_the_spend_ledger_accepts_the_wrap_up_task_and_still_refuses_an_unknown_one(db_url: str) -> None:
    insert = ("INSERT INTO inference_calls (task, provider, model, outcome, duration_ms) "
              "VALUES (%s, 'p', 'm', 'ok', 1)")
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(insert.encode(), ("wrap_up",))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(insert.encode(), ("no_such_task",))
        conn.execute(insert.encode(), ("chat",))

"""When the person last typed into a session: read from Claude Code's transcript, minus the prompts the bridge sent.

The record shapes are the ones real transcripts hold (keys and `type`/`origin`/`promptSource` values read from them);
every text and id here is made up."""

import json
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

import pytest
from herdr_bridge import transcripts
from herdr_bridge.jsonget import items
from herdr_bridge import ledger as ledger_module
from herdr_bridge.ledger import EARLY_S, LATE_S, RETENTION_S, Ledger, digest
from herdr_bridge.runner import Outcome
from herdr_bridge.transcripts import Transcripts, typed_entry

from herdr_bridge_support import THROWAWAY, Bridge, FakeHerdr, listing, ok, session_ids

LIST = ("agent", "list")
TABS = ("tab", "list")
NOW = 1_700_000_000.0
ALPHA, BETA = session_ids()[0], session_ids()[2]
PANE = "w5H:pK"


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def user(at: float, content: object = "typed words", **fields: object) -> dict[str, object]:
    """A typed message as a transcript records it, with `fields` replacing or adding to its keys."""
    record: dict[str, object] = {
        "parentUuid": None, "isSidechain": False, "userType": "external", "entrypoint": "cli", "cwd": "/w",
        "sessionId": ALPHA, "type": "user", "message": {"role": "user", "content": content},
        "origin": {"kind": "human"}, "promptSource": "typed", "turnOrigin": "human", "timestamp": iso(at)}
    record.update(fields)
    return record


def tool_result(at: float) -> dict[str, object]:
    return {"type": "user", "isSidechain": False, "timestamp": iso(at), "toolUseResult": {"stdout": "x"},
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "out"}]}}


def assistant(at: float) -> dict[str, object]:
    return {"type": "assistant", "timestamp": iso(at), "message": {"role": "assistant", "content": [
        {"type": "text", "text": "reply"}]}}


def write(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records))


def append(path: Path, records: list[dict[str, object]]) -> None:
    with path.open("a") as f:
        f.write("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records))


def made(tmp_path: Path, extra: Mapping[tuple[str, ...], Outcome | Exception] | None = None) -> Bridge:
    replies: dict[tuple[str, ...], Outcome | Exception] = {
        LIST: listing(), TABS: ok("tab_list.json"), ("agent", "prompt", PANE, "reply with ok"): ok("agent_prompt.json")}
    replies.update(extra or {})
    (tmp_path / "state").mkdir()
    return Bridge(tmp_path / "state", FakeHerdr(replies), clock=lambda: NOW)


def transcript(b: Bridge, session: str = ALPHA, project: str = "-w-proj") -> Path:
    return b.projects / project / f"{session}.jsonl"


def listed(b: Bridge) -> dict[str, object]:
    return b.get("/v1/sessions").body


def typed_of(b: Bridge, session: str = ALPHA) -> object:
    [one] = [s for s in items(listed(b)["sessions"]) if s["id"] == session]
    return one["last_typed_at"]


def test_the_latest_typed_message_is_the_sessions_time_and_the_lists(tmp_path: Path) -> None:
    b = made(tmp_path)
    write(transcript(b), [user(NOW - 300), assistant(NOW - 290), user(NOW - 100, [{"type": "text", "text": "words"}]),
                          assistant(NOW - 90)])
    assert typed_of(b) == iso(NOW - 100)
    assert listed(b)["last_typed_at"] == iso(NOW - 100)


def test_the_list_time_is_the_latest_across_sessions_and_a_session_without_a_transcript_is_null(tmp_path: Path) -> None:
    b = made(tmp_path)
    write(transcript(b), [user(NOW - 500)])
    write(transcript(b, BETA, "-other"), [user(NOW - 40)])
    assert typed_of(b, ALPHA) == iso(NOW - 500)
    assert typed_of(b, BETA) == iso(NOW - 40)
    assert typed_of(b, THROWAWAY) is None
    assert listed(b)["last_typed_at"] == iso(NOW - 40)


def test_nothing_readable_is_null(tmp_path: Path) -> None:
    b = made(tmp_path)
    assert typed_of(b) is None and listed(b)["last_typed_at"] is None
    write(transcript(b), [assistant(NOW), tool_result(NOW)])
    assert typed_of(b) is None
    transcript(b).write_bytes(b"not json\n\xff\xfe\n{}\n")
    assert typed_of(b) is None


@pytest.mark.parametrize("record", [
    tool_result(NOW),
    user(NOW, isMeta=True),
    user(NOW, isCompactSummary=True),
    user(NOW, isSidechain=True),
    user(NOW, origin={"kind": "peer", "name": "a", "body": "b"}, promptSource="system", turnOrigin="peer"),
    user(NOW, origin={"kind": "task-notification", "producer": "session-task"}, promptSource="system"),
    user(NOW, origin=None, promptSource="sdk", turnOrigin="sdk", entrypoint="sdk-cli"),
    user(NOW, message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "c"}]}),
    user(NOW, timestamp="yesterday"),
    {"type": "last-prompt", "sessionId": ALPHA},
    assistant(NOW),
], ids=["tool_result", "meta", "compact", "sidechain", "peer", "task_notification", "sdk", "tool_result_block",
        "bad_timestamp", "bookkeeping", "assistant"])
def test_a_record_that_is_not_a_person_typing_is_not_counted(record: dict[str, object]) -> None:
    assert typed_entry(json.dumps(record, separators=(",", ":")).encode()) is None


@pytest.mark.parametrize("fields", [{}, {"promptSource": "queued"}, {"origin": None, "promptSource": None, "turnOrigin": None}])
def test_typed_queued_and_older_records_without_the_newer_fields_are_counted(fields: dict[str, object]) -> None:
    entry = typed_entry(json.dumps(user(NOW, **fields), separators=(",", ":")).encode())
    assert entry is not None and entry.at == iso(NOW)


def test_an_image_alone_is_a_typed_message(tmp_path: Path) -> None:
    b = made(tmp_path)
    write(transcript(b), [user(NOW - 9, [{"type": "image", "source": {"type": "base64"}}])])
    assert typed_of(b) == iso(NOW - 9)


def test_a_prompt_the_bridge_sent_is_not_the_person_typing(tmp_path: Path) -> None:
    b = made(tmp_path)
    write(transcript(b), [user(NOW - 600, "my own words")])
    assert b.post(f"/v1/sessions/{THROWAWAY}/prompt", {"text": "reply with ok"}).body == {"submitted": True}
    write(transcript(b, THROWAWAY), [user(NOW + 2, "reply with ok\n")])
    assert typed_of(b, THROWAWAY) is None
    assert listed(b)["last_typed_at"] == iso(NOW - 600)


def test_her_prompt_is_skipped_and_the_person_before_it_is_found(tmp_path: Path) -> None:
    b = made(tmp_path)
    b.post(f"/v1/sessions/{THROWAWAY}/prompt", {"text": "reply with ok"})
    path = transcript(b, THROWAWAY)
    write(path, [user(NOW - 600), user(NOW + 3, "reply with ok"), assistant(NOW + 9)])
    assert typed_of(b, THROWAWAY) == iso(NOW - 600)


def test_the_same_words_typed_long_after_her_prompt_count(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "sent.jsonl", lambda: NOW)
    ledger.record(ALPHA, "continue")
    path = tmp_path / "p" / f"{ALPHA}.jsonl"
    write(path, [user(NOW + 1, "continue"), user(NOW + LATE_S + 60, "continue")])
    assert Transcripts(tmp_path, ledger).last_typed(ALPHA) == iso(NOW + LATE_S + 60)


def test_a_ledger_entry_matches_one_session_one_text_and_a_window_of_time(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "sent.jsonl", lambda: NOW)
    ledger.record(ALPHA, "  hello  ")
    h = digest("hello")
    assert ledger.was_sent(ALPHA, h, NOW)
    assert ledger.was_sent(ALPHA, h, NOW - EARLY_S) and ledger.was_sent(ALPHA, h, NOW + LATE_S)
    assert not ledger.was_sent(ALPHA, h, NOW - EARLY_S - 1) and not ledger.was_sent(ALPHA, h, NOW + LATE_S + 1)
    assert not ledger.was_sent(BETA, h, NOW) and not ledger.was_sent(ALPHA, digest("bye"), NOW)


def test_the_ledger_keeps_digests_not_text_and_survives_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "state" / "sent.jsonl"
    Ledger(path, lambda: NOW).record(ALPHA, "a secret sentence")
    assert "secret" not in path.read_text()
    assert Ledger(path, lambda: NOW).was_sent(ALPHA, digest("a secret sentence"), NOW)


def test_the_ledger_drops_what_is_old_and_what_is_over_the_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ledger_module, "MAX_ENTRIES", 10)
    path = tmp_path / "sent.jsonl"
    now = [NOW]
    ledger = Ledger(path, lambda: now[0])
    ledger.record(ALPHA, "old")
    now[0] = NOW + RETENTION_S + 1
    ledger.record(ALPHA, "new")
    assert len(path.read_text().splitlines()) == 1
    for i in range(15):
        ledger.record(ALPHA, f"p{i}")
    assert len(path.read_text().splitlines()) == 10
    assert ledger.was_sent(ALPHA, digest("p14"), now[0]) and not ledger.was_sent(ALPHA, digest("p4"), now[0])


def test_a_damaged_ledger_line_is_ignored_and_not_fatal(tmp_path: Path) -> None:
    path = tmp_path / "sent.jsonl"
    path.write_text('garbage\n{"s": 1}\n[]\n')
    ledger = Ledger(path, lambda: NOW)
    ledger.record(ALPHA, "x")
    assert len(path.read_text().splitlines()) == 1


def test_only_new_bytes_are_read_and_a_line_still_being_written_waits(tmp_path: Path) -> None:
    path = tmp_path / "p" / f"{ALPHA}.jsonl"
    t = Transcripts(tmp_path, Ledger(tmp_path / "sent.jsonl"))
    write(path, [user(NOW - 50)])
    assert t.last_typed(ALPHA) == iso(NOW - 50)
    half = json.dumps(user(NOW - 10), separators=(",", ":"))
    with path.open("a") as f:
        f.write(half[:30])
    assert t.last_typed(ALPHA) == iso(NOW - 50)
    with path.open("a") as f:
        f.write(half[30:] + "\n")
    assert t.last_typed(ALPHA) == iso(NOW - 10)
    append(path, [assistant(NOW)])
    assert t.last_typed(ALPHA) == iso(NOW - 10)
    assert t.seen[ALPHA].read_to == path.stat().st_size


def test_a_transcript_that_shrank_is_read_again_from_the_start(tmp_path: Path) -> None:
    path = tmp_path / "p" / f"{ALPHA}.jsonl"
    t = Transcripts(tmp_path, Ledger(tmp_path / "sent.jsonl"))
    write(path, [user(NOW - 50), assistant(NOW - 40), assistant(NOW - 30)])
    assert t.last_typed(ALPHA) == iso(NOW - 50)
    write(path, [user(NOW - 5)])
    assert t.last_typed(ALPHA) == iso(NOW - 5)


def test_lines_longer_than_a_chunk_are_read_whole(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transcripts, "CHUNK", 64)
    path = tmp_path / "p" / f"{ALPHA}.jsonl"
    big = user(NOW - 1, "w" * 500)
    write(path, [user(NOW - 90), big, tool_result(NOW), assistant(NOW)])
    assert Transcripts(tmp_path, Ledger(tmp_path / "sent.jsonl")).last_typed(ALPHA) == iso(NOW - 1)
    write(path, [user(NOW - 90), tool_result(NOW), assistant(NOW)])
    assert Transcripts(tmp_path, Ledger(tmp_path / "sent.jsonl")).last_typed(ALPHA) == iso(NOW - 90)


def test_the_newest_transcript_wins_and_a_non_uuid_id_names_no_file(tmp_path: Path) -> None:
    t = Transcripts(tmp_path, Ledger(tmp_path / "sent.jsonl"))
    old, new = tmp_path / "a" / f"{ALPHA}.jsonl", tmp_path / "b" / f"{ALPHA}.jsonl"
    write(old, [user(NOW - 900)])
    write(new, [user(NOW - 20)])
    os.utime(old, (NOW - 100, NOW - 100))
    assert t.last_typed(ALPHA) == iso(NOW - 20)
    assert t.last_typed("../../etc/passwd") is None
    assert t.find("*") is None


def test_the_call_log_never_carries_transcript_text(tmp_path: Path) -> None:
    b = made(tmp_path)
    write(transcript(b), [user(NOW - 5, "private words about the day")])
    listed(b)
    assert b.log.lines and all("private" not in line and iso(NOW - 5) not in line for line in b.log.lines)

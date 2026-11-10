"""`python -m ashley.memory report --conversation N`: bad arguments exit 2 with a usage message, anything else exits 0
and prints the report from the log lines on stdin. Run in process. Written blind from the contract."""

import asyncio
import io
import sys

import pytest
from ashley.memory.__main__ import main
from ashley.memory.model import Add, Update
from ashley.memory.postgres import PostgresMemory

from memory_support import pool
from profile_support import AT, LATER, new, seated
from report_support import applied, at, done, line

MARK = "zqCLITEXT"


def cli(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], stdin: list[str], *argv: str,
        url: str | None = None) -> tuple[int, str, str]:
    if url is not None:
        monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(sys, "stdin", io.StringIO("".join(ln + "\n" for ln in stdin)))
    capsys.readouterr()
    try:
        code = main(list(argv))
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.mark.parametrize("argv", [
    [], ["report"], ["report", "--conversation"], ["report", "--conversation", "abc"],
    ["report", "--conversation", "1.5"], ["report", "--conversation", ""], ["bogus", "--conversation", "1"],
    ["--conversation", "1"], ["report", "--conversation", "1", "--bogus"], ["report", "--conversation", "1", "extra"],
])
def test_bad_arguments_exit_two_with_a_usage_message(monkeypatch: pytest.MonkeyPatch,
                                                      capsys: pytest.CaptureFixture[str], argv: list[str]) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
    code, out, err = cli(monkeypatch, capsys, [done(1)], *argv)
    assert code == 2
    assert err.strip() and out == ""


def test_the_report_of_a_conversation_prints_the_facts_she_was_offered(db_url: str, monkeypatch: pytest.MonkeyPatch,
                                                                       capsys: pytest.CaptureFixture[str]) -> None:
    c = seated(db_url)

    async def scenario() -> tuple[int, ...]:
        async with pool(db_url) as db:
            memory = PostgresMemory(db)
            a, b = await memory.apply(c.home, c.talk, [Add(new(c.alana, f"{MARK} standing")),
                                                       Add(new(c.alana, f"{MARK} recalled", standing=False))], AT)
            await memory.apply(c.home, c.talk, [Update(b, new(c.alana, f"{MARK} replacement", standing=False))], LATER)
            return a, b

    a, b = asyncio.run(asyncio.wait_for(scenario(), 25))
    lines = [line("http.request", method="GET", status=200), "Traceback (most recent call last):", "",
             done(c.talk, at(1), standing=str(a), recalled=str(b), used=str(b)),
             done(c.talk + 500, at(2), standing="", recalled=""), applied(c.talk, at(3), inserted=str(a), add=1)]
    code, out, err = cli(monkeypatch, capsys, lines, "report", "--conversation", str(c.talk), url=db_url)
    assert code == 0, err
    assert f"{MARK} standing" in out and f"{MARK} recalled" in out
    assert str(a) in out and str(b) in out and "replaced by" in out and "used" in out


def test_a_forgotten_fact_and_the_writer_are_reported(db_url: str, monkeypatch: pytest.MonkeyPatch,
                                                      capsys: pytest.CaptureFixture[str]) -> None:
    from conversations_support import scalar
    c = seated(db_url)
    scalar(db_url, "INSERT INTO inference_calls (task, provider, model, outcome, duration_ms, conversation_id) "
                   "VALUES ('memory_write', 'prov', 'writer-model-z', 'ok', 5, %s) RETURNING id", (c.talk,))
    code, out, err = cli(monkeypatch, capsys, [done(c.talk, at(1), standing="987654", recalled="")],
                         "report", "--conversation", str(c.talk), url=db_url)
    assert code == 0, err
    assert "987654" in out and "forgotten" in out and "writer-model-z" in out


def test_nothing_found_exits_zero_and_says_so(db_url: str, monkeypatch: pytest.MonkeyPatch,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = cli(monkeypatch, capsys, [done(3), "noise"], "report", "--conversation", "99", url=db_url)
    assert code == 0, err
    assert out.strip() and "99" in out


def test_empty_stdin_exits_zero(db_url: str, monkeypatch: pytest.MonkeyPatch,
                                capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = cli(monkeypatch, capsys, [], "report", "--conversation", "5", url=db_url)
    assert code == 0 and out.strip()

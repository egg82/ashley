"""Directed tests for PostgresPeople and the admin CLI, against a migrated database."""

from pathlib import Path

import psycopg
import pytest
from ashley.db.pool import PoolDatabase
from ashley.people import admin
from ashley.people.__main__ import main
from ashley.people.model import Account, Person
from ashley.people.people import PeopleUnavailable
from ashley.people.postgres import PostgresPeople

from conversations_support import run, scalar


def cli(url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    monkeypatch.setenv("DATABASE_URL", url)
    code = main(list(argv))
    return code, capsys.readouterr().out.strip()


def test_the_cli_builds_a_household_the_service_reads(db_url: str, monkeypatch: pytest.MonkeyPatch,
                                                      capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    profile = tmp_path / "profile.txt"
    profile.write_text("Two adults and a cat.", encoding="utf-8")
    code, hid = cli(db_url, monkeypatch, capsys, "add-household", "home", "--timezone", "America/Denver")
    assert code == 0
    assert cli(db_url, monkeypatch, capsys, "set-profile", hid, str(profile))[0] == 0
    _, alana = cli(db_url, monkeypatch, capsys, "add-person", hid, "Alana")
    _, sam = cli(db_url, monkeypatch, capsys, "add-person", hid, "Sam")
    _, account = cli(db_url, monkeypatch, capsys, "add-account", alana, "home_assistant", "person.alana")
    code, listed = cli(db_url, monkeypatch, capsys, "list", hid)
    assert code == 0
    assert listed.splitlines() == [f"{alana}\tAlana\thome_assistant\tperson.alana", f"{sam}\tSam\t-\t-"]

    async def scenario() -> None:
        db = PoolDatabase(db_url)
        await db.open()
        try:
            people = PostgresPeople(db)
            household = await people.household(int(hid))
            assert household is not None
            assert (household.name, household.timezone, household.profile) == ("home", "America/Denver", "Two adults and a cat.")
            assert household.people == (Person(int(alana), int(hid), "Alana"), Person(int(sam), int(hid), "Sam"))
            assert await people.household(int(hid) + 1) is None
            assert await people.person_for("home_assistant", "person.alana") == household.people[0]
            assert await people.person_for("home_assistant", "person.sam") is None
            assert await people.person_for("discord", "person.alana") is None
            assert await people.accounts(int(hid), "home_assistant") == (
                Account(int(account), int(hid), int(alana), "home_assistant", "person.alana"),)
            assert await people.accounts(int(hid), "discord") == ()
        finally:
            await db.close()

    run(scenario())


def test_the_cli_refuses_without_writing(db_url: str, monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(db_url, monkeypatch, capsys, "add-household", "home", "--timezone", "Mars/Olympus")[0] == 1
    assert scalar(db_url, "SELECT count(*) FROM households") == 0
    _, hid = cli(db_url, monkeypatch, capsys, "add-household", "home", "--timezone", "UTC")
    _, pid = cli(db_url, monkeypatch, capsys, "add-person", hid, "Alana")
    assert cli(db_url, monkeypatch, capsys, "add-account", pid, "discord", "1")[0] == 0
    assert cli(db_url, monkeypatch, capsys, "add-account", pid, "discord", "1")[0] == 1   # already mapped
    assert cli(db_url, monkeypatch, capsys, "add-account", pid, "Bad System", "2")[0] == 1
    assert cli(db_url, monkeypatch, capsys, "add-account", "999", "discord", "3")[0] == 1
    assert cli(db_url, monkeypatch, capsys, "add-person", "999", "Nobody")[0] == 1
    assert cli(db_url, monkeypatch, capsys, "set-profile", hid, "/no/such/file")[0] == 1
    assert scalar(db_url, "SELECT count(*) FROM accounts") == 1
    assert scalar(db_url, "SELECT count(*) FROM people") == 1


def test_an_unreachable_database_is_unavailable() -> None:
    async def scenario() -> None:
        db = PoolDatabase("postgresql://nobody@127.0.0.1:1/none?connect_timeout=1", connect_timeout_s=0.5)
        await db.open()
        try:
            with pytest.raises(PeopleUnavailable):
                await PostgresPeople(db).household(1)
        finally:
            await db.close()

    run(scenario())


def test_an_account_joins_its_persons_household(db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        hid = admin.add_household(conn, "a", "UTC")
        other = admin.add_household(conn, "b", "UTC")
        pid = admin.add_person(conn, hid, "Alana")
        admin.add_account(conn, pid, "discord", "1")
        assert other != hid
    assert scalar(db_url, "SELECT household_id FROM accounts") == hid

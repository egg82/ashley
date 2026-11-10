"""A person's own code host connection end to end through the real app, a real database and fake forges: a person
connects their GitLab (any address https) or GitHub with a token the forge answers for, replaces and removes it; only
that person lists it or opens it, the household's other people and other households see none of it; a token the forge
turns away, a host that does not answer, an address that is not https, or what is not the forge stores nothing; the
token is on no wire back and in no log line; a stored secret does not open under another person's name; one person
holds one of each kind, two people two."""

import asyncio
import base64
from collections.abc import Generator

import httpx2
import psycopg
import pytest
from ashley import logs, services
from ashley.api.connection_models import ConnectionRefused, HouseholdConnection
from ashley.codehost import config as codehost_config
from ashley.codehost.github import API, GitHubHost
from ashley.codehost.gitlab import GitLabHost
from ashley.codehost.host import CodeHost
from ashley.codehost.routed import RoutedCodeHost
from ashley.codehost.wire import Wire
from ashley.connections.connections import Connections, ConnectionsUnavailable
from ashley.connections.postgres import PostgresConnections
from ashley.connections.sealing import VERSION, Sealer
from ashley.db.pool import PoolDatabase
from ashley.main import create_app
from ashley.settings import Settings
from ashley.sure.client import Sure
from codehost_support import TOKEN, FakeGitHub, FakeGitLab, Forge, repo_files
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from fastapi.testclient import TestClient
from money_support import FakeSure
from test_connections_routes import APP_KEY, ORIGIN, PUBLIC, Homes, as_, homes as homes, listed
from connection_legacy_support import opened_of
from connection_routes_support import delete_kind, put_kind

LAB = "https://git.house.test"
CONFIG = codehost_config.load()


def _wire(fake: Forge) -> Wire:
    return Wire(httpx2.AsyncClient(transport=fake.transport(), follow_redirects=False), 5)


@pytest.fixture
def forges() -> tuple[FakeGitLab, FakeGitHub]:
    return FakeGitLab({"a/b": repo_files()}), FakeGitHub({"a/b": repo_files()})


@pytest.fixture
def client(db_url: str, homes: Homes, forges: tuple[FakeGitLab, FakeGitHub]) -> Generator[TestClient]:
    services.unregister(Connections)
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC, connections_key=APP_KEY))
    services.register(Sure, FakeSure().client())
    services.register(CodeHost, RoutedCodeHost({"gitlab": GitLabHost(_wire(forges[0]), CONFIG),
                                                "github": GitHubHost(_wire(forges[1]), CONFIG)}))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        as_(c, homes.alana_token)
        yield c
    for interface in (Sure, Connections, CodeHost):
        services.unregister(interface)


def lab(client: TestClient, base: str = LAB, token: str = TOKEN) -> HouseholdConnection | ConnectionRefused:
    got = put_kind(client, "gitlab", json={"base_url": base, "token": token}, headers=ORIGIN)
    assert token not in got.text
    if got.status_code == 400:
        return ConnectionRefused.model_validate(got.json())
    assert got.status_code == 200, got.text
    return HouseholdConnection.model_validate(got.json())


def hub(client: TestClient, token: str = TOKEN) -> HouseholdConnection | ConnectionRefused:
    got = put_kind(client, "github", json={"token": token}, headers=ORIGIN)
    assert token not in got.text
    if got.status_code == 400:
        return ConnectionRefused.model_validate(got.json())
    assert got.status_code == 200, got.text
    return HouseholdConnection.model_validate(got.json())


def test_a_person_connects_their_gitlab_and_github_and_only_they_see_them(client: TestClient, homes: Homes,
                                                                          forges: tuple[FakeGitLab, FakeGitHub],
                                                                          db_url: str) -> None:
    made = lab(client, LAB + "/")
    assert isinstance(made, HouseholdConnection) and made.kind == "gitlab" and made.base_url == LAB and made.personal
    assert made.added_by is not None and made.added_by.id == homes.alana
    github = hub(client)
    assert isinstance(github, HouseholdConnection) and github.base_url == API
    assert [c.kind for c in listed(client).connections] == ["github", "gitlab"]
    assert forges[0].seen[-1][1] == "/api/v4/user" and forges[1].seen[-1][1] == "/user"
    as_(client, homes.sam_token)
    assert listed(client).connections == []
    assert delete_kind(client, "gitlab", headers=ORIGIN).status_code == 404
    as_(client, homes.kim_token)
    assert listed(client).connections == []
    as_(client, homes.alana_token)
    assert delete_kind(client, "gitlab", headers=ORIGIN).status_code == 204
    assert [c.kind for c in listed(client).connections] == ["github"]
    assert scalar(db_url, "SELECT count(*) FROM connections") == 1


def test_two_people_each_hold_their_own_and_a_replacement_keeps_one(client: TestClient, homes: Homes,
                                                                    db_url: str) -> None:
    lab(client)
    as_(client, homes.sam_token)
    lab(client)
    assert scalar(db_url, "SELECT count(*) FROM connections WHERE kind = 'gitlab'") == 2
    again = lab(client)
    assert isinstance(again, HouseholdConnection) and again.added_by is not None and again.added_by.id == homes.sam
    assert scalar(db_url, "SELECT count(*) FROM connections WHERE kind = 'gitlab'") == 2


def test_what_the_forge_does_not_pass_stores_nothing(client: TestClient, forges: tuple[FakeGitLab, FakeGitHub],
                                                     db_url: str) -> None:
    refused = lab(client, token="a-token-gitlab-turns-away")
    assert isinstance(refused, ConnectionRefused) and refused.reason == "key_refused"
    forges[0].down = 503
    down = lab(client)
    assert isinstance(down, ConnectionRefused) and down.reason == "unreachable"
    plain = lab(client, base="http://git.house.test")
    assert isinstance(plain, ConnectionRefused) and plain.reason == "bad_url"
    forges[1].down = 503
    hub_down = hub(client)
    assert isinstance(hub_down, ConnectionRefused) and hub_down.reason == "unreachable"
    assert scalar(db_url, "SELECT count(*) FROM connections") == 0


def test_the_token_reaches_no_log_line(client: TestClient, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    lab(client)
    hub(client)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("ts=")]
    assert sum("event=connections.connected" in ln for ln in lines) == 2
    assert not any(TOKEN in ln or "git.house.test" in ln for ln in lines)


def test_the_database_holds_the_sealed_token_bound_to_its_person(client: TestClient, homes: Homes, db_url: str) -> None:
    lab(client)
    assert TOKEN.encode() not in bytes(scalar(db_url, "SELECT secret FROM connections"))
    household = scalar(db_url, f"SELECT household_id FROM people WHERE id = {homes.alana}")

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        try:
            key = Sealer({VERSION: base64.b64decode(APP_KEY)})
            connections = PostgresConnections(database, key)
            mine = await opened_of(connections, household, "gitlab", homes.alana)
            assert mine is not None and mine.secret == TOKEN and mine.connection.person_id == homes.alana
            assert await opened_of(connections, household, "gitlab", homes.sam) is None
            assert await opened_of(connections, household, "gitlab") is None
            with psycopg.connect(db_url) as conn:
                conn.execute("UPDATE connections SET person_id = %s WHERE kind = 'gitlab'", (homes.sam,))
            with pytest.raises(ConnectionsUnavailable):
                await opened_of(connections, household, "gitlab", homes.sam)
        finally:
            await database.close()

    asyncio.run(scenario())

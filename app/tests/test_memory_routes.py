"""The memory routes through the real app and a real database: a signed-in person sees the facts that concern them and
nothing the visibility rules hide, corrects one by superseding it from a web conversation of its own, and forgets one
with every version it replaced; anything not theirs is 404, exactly as a fact that does not exist."""

from collections.abc import Generator
from dataclasses import dataclass, field

import httpx2
import psycopg
import pytest
from ashley import logs
from ashley.api.models import ErrorResponse, ForgetResponse, MemoryFact, MemoryFactsResponse
from ashley.api.models import Person as PersonModel
from ashley.api.person import person_signed_in
from ashley.main import create_app
from ashley.people import admin
from ashley.people.model import Person
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from contract.conversations_support import db_url as db_url, events, migrated_template as migrated_template
from contract.conversations_support import scalar
from fastapi.testclient import TestClient

PUBLIC = "https://ashley.test"


@dataclass
class Home:
    url: str
    id: int
    alana: int
    ella: int
    talk: int
    as_: list[int] = field(default_factory=list[int])

    def sign_in(self, person_id: int) -> None:
        self.as_[:] = [person_id]

    def fact(self, about: int | None, owner: int | None, text: str, visibility: str = "shared",
             kind: str = "preference", replaces: int | None = None) -> int:
        """A current fact, learned in `talk`; with `replaces`, that fact is closed and points at this one."""
        new = int(scalar(self.url, "INSERT INTO facts (household_id, about_id, owner_id, visibility, visibility_stated, "
                                   "kind, standing, text, source_conversation_id, valid_from) "
                                   "VALUES (%s, %s, %s, %s, false, %s, false, %s, %s, now()) RETURNING id",
                         (self.id, about, owner, visibility, kind, text, self.talk)))
        if replaces is not None:
            scalar(self.url, "UPDATE facts SET valid_to = now(), superseded_by = %s WHERE id = %s RETURNING id",
                   (new, replaces))
        return new


@pytest.fixture
def home(db_url: str) -> Home:
    with psycopg.connect(db_url) as conn:
        hid = admin.add_household(conn, "home", "America/Denver")
        alana, ella = admin.add_person(conn, hid, "Alana"), admin.add_person(conn, hid, "Ella")
    talk = int(scalar(db_url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id", (hid,)))
    scalar(db_url, "INSERT INTO conversation_participants VALUES (%s, %s, %s) RETURNING person_id", (talk, hid, ella))
    return Home(db_url, hid, alana, ella, talk, [alana])


@pytest.fixture
def client(home: Home) -> Generator[TestClient]:
    app = create_app(Settings(database_url=home.url, build_version="t", public_url=PUBLIC))
    names = {home.alana: "Alana", home.ella: "Ella"}
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, Person(home.as_[0], home.id, names[home.as_[0]]))
    with TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}) as c:
        yield c


def listed(client: TestClient) -> dict[int, MemoryFact]:
    got = client.get("/api/memory/facts")
    assert got.status_code == 200
    return {f.id: f for f in MemoryFactsResponse.model_validate(got.json()).items}


def every_fact(url: str) -> str:
    return str(scalar(url, "SELECT coalesce(string_agg(f::text, '|' ORDER BY id), '') FROM facts f"))


def test_no_session_is_401_on_every_route(home: Home) -> None:
    app = create_app(Settings(database_url=home.url, build_version="t", public_url=PUBLIC))
    with TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}) as c:
        for response in (c.get("/api/memory/facts"), c.delete("/api/memory/facts/1"),
                         c.post("/api/memory/facts/1/corrections", json={"text": "x"})):
            assert response.status_code == 401
            assert ErrorResponse.model_validate(response.json()).code == "unauthorized"


def test_a_person_sees_what_concerns_them_with_names_its_predecessor_and_source(client: TestClient, home: Home) -> None:
    tea = home.fact(home.alana, home.alana, "Alana likes tea", "private")
    coffee = home.fact(home.alana, home.alana, "Alana likes coffee", "private", replaces=tea)
    told = home.fact(home.alana, home.ella, "Alana is learning piano", "discreet")
    house = home.fact(None, None, "Mochi is fed at six")
    party = home.fact(home.alana, home.ella, "Ella is planning Alana's party", "private")
    jazz = home.fact(home.ella, home.ella, "Ella likes jazz")
    seen = listed(client)
    assert set(seen) == {coffee, told, house}
    replaced = seen[coffee].replaced
    assert replaced is not None and replaced.text == "Alana likes tea"
    about, owner = seen[told].about, seen[told].owner
    assert about is not None and owner is not None and (about.name, owner.name) == ("Alana", "Ella")
    assert (seen[house].about, seen[house].owner, seen[house].replaced) == (None, None, None)
    assert (seen[told].source.conversation_id, seen[told].source.took_part) == (home.talk, False)
    assert (seen[told].source.channel, seen[told].source.place) == (None, None)
    scalar(home.url, "UPDATE conversations SET channel = 'voice', place = 'kitchen' WHERE id = %s RETURNING id", (home.talk,))
    assert (listed(client)[told].source.channel, listed(client)[told].source.place) == ("voice", "kitchen")
    home.sign_in(home.ella)
    assert set(listed(client)) == {told, house, party, jazz}


def test_a_correction_supersedes_from_a_web_conversation_of_its_own(client: TestClient, home: Home) -> None:
    tea = home.fact(home.alana, home.alana, "Alana likes tea", "discreet", kind="health")
    made = client.post(f"/api/memory/facts/{tea}/corrections", json={"text": "Alana likes green tea"})
    assert made.status_code == 201
    new = MemoryFact.model_validate(made.json())
    assert (new.text, new.kind, new.visibility) == ("Alana likes green tea", "health", "discreet")
    assert new.replaced is not None and new.replaced.text == "Alana likes tea"
    assert (new.source.conversation_kind, new.source.took_part) == ("command", True)
    assert (new.source.channel, new.source.place) == ("web", None)
    assert scalar(home.url, "SELECT superseded_by FROM facts WHERE id = %s", (tea,)) == new.id
    talk = new.source.conversation_id
    assert scalar(home.url, "SELECT remembered FROM conversations WHERE id = %s", (talk,)) is False
    assert scalar(home.url, "SELECT array_agg(author || ':' || speaker_id || ':' || text) FROM turns "
                            "WHERE conversation_id = %s", (talk,)) == [f"person:{home.alana}:Alana likes green tea"]
    assert set(listed(client)) == {new.id}


def test_anything_not_theirs_is_404_and_changes_nothing(client: TestClient, home: Home) -> None:
    secret = home.fact(home.alana, home.ella, "Ella is planning Alana's party", "private")
    ellas = home.fact(home.ella, home.ella, "Ella likes jazz")
    closed = home.fact(home.alana, home.alana, "Alana owned a kiln")
    home.fact(home.alana, home.alana, "Alana sold the kiln", replaces=closed)
    before = every_fact(home.url)
    for target in (secret, ellas, closed, 999999):
        for response in (client.post(f"/api/memory/facts/{target}/corrections", json={"text": "changed"}),
                         client.delete(f"/api/memory/facts/{target}")):
            assert response.status_code == 404, target
            assert ErrorResponse.model_validate(response.json()).code == "not_found"
    assert every_fact(home.url) == before


def test_only_the_owner_changes_who_may_know(client: TestClient, home: Home) -> None:
    told = home.fact(home.alana, home.ella, "Alana is learning piano", "discreet")
    mine = home.fact(home.alana, home.alana, "Alana likes tea")
    before = every_fact(home.url)
    refused = client.post(f"/api/memory/facts/{told}/corrections", json={"text": "Alana plays piano",
                                                                        "visibility": "shared"})
    assert (refused.status_code, refused.json()["code"]) == (403, "forbidden")
    assert every_fact(home.url) == before
    kept = client.post(f"/api/memory/facts/{told}/corrections", json={"text": "Alana plays piano",
                                                                     "visibility": "discreet"})
    assert kept.status_code == 201 and MemoryFact.model_validate(kept.json()).owner is not None
    made = client.post(f"/api/memory/facts/{mine}/corrections", json={"text": "Alana likes tea", "visibility": "private"})
    assert MemoryFact.model_validate(made.json()).visibility == "private"


def test_anyone_in_the_household_corrects_a_household_fact(client: TestClient, home: Home) -> None:
    house = home.fact(None, None, "Mochi is fed at six")
    home.sign_in(home.ella)
    made = client.post(f"/api/memory/facts/{house}/corrections", json={"text": "Mochi is fed at seven"})
    assert made.status_code == 201
    assert MemoryFact.model_validate(made.json()).visibility == "shared"


def move(client: TestClient, fact: int, to: str) -> httpx2.Response:
    return client.post(f"/api/memory/facts/{fact}/moves", json={"to": to})


def test_an_owner_makes_their_fact_the_households_and_nobody_else_has_it_before(client: TestClient, home: Home) -> None:
    litter = home.fact(None, home.alana, "The household runs out of cat litter by the second weekend", "private")
    made = move(client, litter, "household")
    assert made.status_code == 201
    new = MemoryFact.model_validate(made.json())
    assert (new.about, new.owner, new.visibility) == (None, None, "shared")
    assert new.replaced is not None and new.source.conversation_kind == "command"
    assert scalar(home.url, "SELECT superseded_by FROM facts WHERE id = %s", (litter,)) == new.id
    home.sign_in(home.ella)
    assert {f.text for f in listed(client).values()} == {"The household runs out of cat litter by the second weekend"}


def test_a_fact_about_its_owner_stays_theirs(client: TestClient, home: Home) -> None:
    medicine = home.fact(home.alana, home.alana, "Alana's blood pressure medicine is at eight", "private")
    before = every_fact(home.url)
    refused = move(client, medicine, "household")
    assert (refused.status_code, ErrorResponse.model_validate(refused.json()).code) == (403, "forbidden")
    assert every_fact(home.url) == before


def test_a_household_member_makes_a_household_fact_theirs_and_it_leaves_the_others_household(client: TestClient,
                                                                                            home: Home) -> None:
    house = home.fact(None, None, "Mochi is fed at six")
    home.sign_in(home.ella)
    made = move(client, house, "mine")
    assert made.status_code == 201
    new = MemoryFact.model_validate(made.json())
    assert (new.about, new.owner, new.text) == (None, PersonModel(id=home.ella, household_id=home.id, name="Ella"),
                                                "Mochi is fed at six")
    assert scalar(home.url, "SELECT owner_id FROM facts WHERE id = %s", (new.id,)) == home.ella
    assert move(client, new.id, "mine").status_code == 403


def test_a_fact_about_or_owned_by_someone_else_does_not_move(client: TestClient, home: Home) -> None:
    about_ella = home.fact(home.ella, home.alana, "Ella likes jazz")
    told_by_ella = home.fact(home.alana, home.ella, "Alana is learning piano")
    mine = home.fact(home.alana, home.alana, "Alana likes tea")
    house = home.fact(None, None, "The boiler is serviced in May")
    before = every_fact(home.url)
    for target, to in ((about_ella, "household"), (told_by_ella, "household"), (told_by_ella, "mine"), (mine, "mine"),
                       (house, "household")):
        refused = move(client, target, to)
        assert (refused.status_code, ErrorResponse.model_validate(refused.json()).code) == (403, "forbidden"), (target, to)
    assert move(client, 999999, "mine").status_code == 404
    assert move(client, mine, "elsewhere").status_code == 422
    assert every_fact(home.url) == before


@pytest.mark.parametrize("body", [{"text": ""}, {"text": "   "}, {"text": "x" * 1001}, {"text": "ok", "kind": "home"},
                                  {"text": "ok", "visibility": "secret"}])
def test_a_body_outside_the_request_is_422(client: TestClient, home: Home, body: dict[str, object]) -> None:
    tea = home.fact(home.alana, home.alana, "Alana likes tea")
    assert client.post(f"/api/memory/facts/{tea}/corrections", json=body).status_code == 422


def test_forget_deletes_every_version_and_logs_only_ids_and_counts(client: TestClient, home: Home,
                                                                   capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    tea = home.fact(home.alana, home.alana, "Alana likes tea")
    coffee = home.fact(home.alana, home.alana, "Alana likes coffee", replaces=tea)
    cocoa = home.fact(home.alana, home.alana, "Alana likes cocoa", replaces=coffee)
    other = home.fact(home.alana, home.alana, "Alana owns a kiln")
    capsys.readouterr()
    gone = client.delete(f"/api/memory/facts/{cocoa}")
    assert gone.status_code == 200 and ForgetResponse.model_validate(gone.json()).deleted == 3
    assert scalar(home.url, "SELECT array_agg(id) FROM facts") == [other]
    assert set(listed(client)) == {other}
    out = capsys.readouterr().out
    (line,) = events(out, "memory.forgotten")
    assert (line["by"], line["deleted"]) == (str(home.alana), "3")
    assert "cocoa" not in out and "Alana likes" not in out


def test_a_nul_in_a_correction_is_422(client: TestClient, home: Home) -> None:
    tea = home.fact(home.alana, home.alana, "Alana likes tea")
    assert client.post(f"/api/memory/facts/{tea}/corrections", json={"text": "a\u0000b"}).status_code == 422


def test_household_money_is_every_members_to_see_correct_and_forget(client: TestClient, home: Home) -> None:
    rent = home.fact(home.alana, None, "Alana's rent is paid on the first", "members", kind="finance")
    home.sign_in(home.ella)
    seen = listed(client)[rent]
    assert (seen.owner, seen.visibility) == (None, "members")
    fixed = client.post(f"/api/memory/facts/{rent}/corrections", json={"text": "The rent is paid on the second"})
    assert fixed.status_code == 201
    new = MemoryFact.model_validate(fixed.json())
    assert (new.owner, new.visibility, new.kind) == (None, "members", "finance")
    home.sign_in(home.alana)
    assert client.delete(f"/api/memory/facts/{new.id}").status_code == 200
    assert listed(client) == {}


def test_a_private_money_fact_made_the_households_is_members_not_shared(client: TestClient, home: Home) -> None:
    savings = home.fact(None, home.alana, "The house deposit fund holds six thousand dollars", "private", kind="finance")
    made = move(client, savings, "household")
    assert made.status_code == 201
    assert MemoryFact.model_validate(made.json()).visibility == "members"
    back = move(client, MemoryFact.model_validate(made.json()).id, "mine")
    assert back.status_code == 201
    assert MemoryFact.model_validate(back.json()).visibility == "private"

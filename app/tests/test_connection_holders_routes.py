"""Handing a connection to the household and taking it back, and sharing or keeping what it reaches, through the real
app: a connection connected through Google lists its mailbox kept; the room lists stored rows and the service is read after its answer; the
owner shares it, hands the connection over (every resource shared) and takes it back; a housemate can do none of the
owner's acts; the refusals carry the statuses `ashley.api.connection_holders` names."""

import asyncio

import httpx2
import pytest
from ashley import services
from ashley.api.connection_models import ConnectionsResponse, HouseholdConnection
from ashley.mail.mailbox import Mailbox
from ashley.mail.model import Account, Draft, Header, Label, MailChange, MailFailed, MailQuery, Message, Page, Target
from fastapi.testclient import TestClient
from starlette.types import Message as Asgi, Scope
from oauth_google_support import FakeGoogle
from oauth_home_support import ORIGIN, Home, as_, client as client, connect, google as google, home as home, start, back
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template

BOX = "alana@gmail.test"


class AddressOnly(Mailbox):
    """Answers the address its owner set (a mail service that is down when `address` is None) and nothing else."""

    def __init__(self) -> None:
        self.address_now: str | None = BOX
        self.asked: list[Account] = []

    def can_read(self, kind: str, scopes: tuple[str, ...]) -> bool:
        return True

    async def address(self, account: Account) -> str:
        self.asked.append(account)
        if self.address_now is None:
            raise MailFailed("unreachable")
        return self.address_now

    async def labels(self, account: Account) -> tuple[Label, ...]:
        raise MailFailed("unreachable")

    async def search(self, account: Account, query: MailQuery) -> Page[Header]:
        raise MailFailed("unreachable")

    async def read(self, account: Account, message_id: str) -> Message:
        raise MailFailed("unreachable")

    def can_change(self, kind: str, scopes: tuple[str, ...]) -> bool:
        return False

    async def draft(self, account: Account, draft: Draft) -> str:
        raise MailFailed("unreachable")

    async def send(self, account: Account, draft: Draft) -> str:
        raise MailFailed("unreachable")

    async def change(self, account: Account, targets: tuple[Target, ...], change: MailChange) -> int:
        raise MailFailed("unreachable")


@pytest.fixture
def mail(client: TestClient) -> AddressOnly:
    mailbox = AddressOnly()
    services.register(Mailbox, mailbox)
    return mailbox


def listed(client: TestClient) -> ConnectionsResponse:
    got = client.get("/api/connections")
    assert got.status_code == 200, got.text
    return ConnectionsResponse.model_validate(got.json())


def patch(client: TestClient, path: str, **body: object) -> httpx2.Response:
    return client.patch(f"/api/connections/{path}", json=body, headers=ORIGIN)


def mine(client: TestClient, google: FakeGoogle, mail: AddressOnly) -> HouseholdConnection:
    assert connect(client, google, "main").endswith("connected")
    [found] = listed(client).connections
    return found


def test_a_new_connection_lists_its_mailbox_kept_and_can_be_handed_over(client: TestClient, google: FakeGoogle,
                                                                       mail: AddressOnly) -> None:
    found = mine(client, google, mail)
    assert [(r.ref, r.kind, r.shared) for r in found.resources] == [(BOX, "mailbox", False)]
    assert found.personal and found.can_hand_over and not found.can_take_back
    kind = next(k for k in listed(client).offered if k.name == "google")
    assert kind.holders == ["household", "person"]


def test_opening_the_room_lists_what_the_service_names_now(client: TestClient, google: FakeGoogle,
                                                           mail: AddressOnly) -> None:
    found = mine(client, google, mail)
    assert patch(client, f"{found.id}/resources/{BOX}", shared=True).status_code == 200
    mail.address_now = "new@gmail.test"
    assert [r.ref for r in listed(client).connections[0].resources] == [BOX], "an opening answers from what is stored"
    assert [(r.ref, r.shared) for r in listed(client).connections[0].resources] == [("new@gmail.test", False)]
    mail.address_now = None
    assert [r.ref for r in listed(client).connections[0].resources] == ["new@gmail.test"], "a silent service drops nothing"


def test_the_room_is_answered_before_any_mail_service_is_asked(client: TestClient, google: FakeGoogle,
                                                               mail: AddressOnly) -> None:
    mine(client, google, mail)
    mail.asked.clear()
    asked_at_answer: list[int] = []
    cookies = "; ".join(f"{c.name}={c.value}" for c in client.cookies.jar)

    async def run() -> None:
        async def receive() -> Asgi:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Asgi) -> None:
            if message["type"] == "http.response.body" and not message.get("more_body"):
                asked_at_answer.append(len(mail.asked))

        scope: Scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
                 "path": "/api/connections", "raw_path": b"/api/connections", "query_string": b"", "root_path": "",
                 "headers": [(b"host", b"ashley.test"), (b"cookie", cookies.encode())], "client": ("127.0.0.1", 1),
                 "server": ("ashley.test", 80)}
        await client.app(scope, receive, send)

    asyncio.run(run())
    assert asked_at_answer == [0] and len(mail.asked) == 1, (asked_at_answer, len(mail.asked))


def test_the_owner_shares_and_keeps_and_a_housemate_cannot(client: TestClient, google: FakeGoogle, mail: AddressOnly,
                                                          home: Home) -> None:
    found = mine(client, google, mail)
    shared = patch(client, f"{found.id}/resources/{BOX}", shared=True)
    assert shared.status_code == 200 and shared.json()["shared"] is True
    as_(client, home.sam_token)
    assert patch(client, f"{found.id}/resources/{BOX}", shared=False).status_code == 404
    assert listed(client).connections == []
    as_(client, home.alana_token)
    assert patch(client, f"{found.id}/resources/{BOX}", shared=False).json()["shared"] is False
    assert patch(client, f"{found.id}/resources/nobody@gmail.test", shared=True).status_code == 404
    assert patch(client, f"{found.id}/resources/{BOX}", shared="maybe").status_code == 422


def test_a_hand_over_and_a_take_back(client: TestClient, google: FakeGoogle, mail: AddressOnly, home: Home) -> None:
    found = mine(client, google, mail)
    handed = patch(client, str(found.id), holder="household")
    assert handed.status_code == 200
    shown = HouseholdConnection.model_validate(handed.json())
    assert not shown.personal and shown.can_take_back and not shown.can_hand_over
    assert [r.shared for r in shown.resources] == [True]
    as_(client, home.sam_token)
    assert [c.id for c in listed(client).connections] == [found.id]
    refused = patch(client, str(found.id), holder="person")
    assert refused.status_code == 403 and refused.json()["code"] == "forbidden"
    kept = patch(client, f"{found.id}/resources/{BOX}", shared=False)
    assert kept.status_code == 409 and kept.json()["code"] == "held_by_household"
    as_(client, home.alana_token)
    back_again = HouseholdConnection.model_validate(patch(client, str(found.id), holder="person").json())
    assert back_again.personal and [r.shared for r in back_again.resources] == [False]
    as_(client, home.sam_token)
    assert listed(client).connections == []
    assert patch(client, str(found.id), holder="household").status_code == 404


def test_a_change_names_a_label_or_a_holder_never_both_or_neither(client: TestClient, google: FakeGoogle,
                                                                 mail: AddressOnly) -> None:
    found = mine(client, google, mail)
    for body in ({}, {"label": "x", "holder": "household"}, {"holder": "nobody"}):
        assert patch(client, str(found.id), **body).status_code == 422
    assert patch(client, str(found.id), label="renamed").json()["label"] == "renamed"


def test_a_move_onto_a_taken_label_is_409_and_moves_nothing(client: TestClient, google: FakeGoogle, mail: AddressOnly,
                                                           home: Home) -> None:
    code, state = start(client, google, "main", holder="household")
    assert back(client, code=code, state=state).endswith("connected")
    household = listed(client).connections[0]
    assert not household.personal and [r.shared for r in household.resources] == [True]
    as_(client, home.sam_token)
    assert connect(client, google, "main").endswith("connected")
    sams = next(c for c in listed(client).connections if c.personal)
    clash = patch(client, str(sams.id), holder="household")
    assert clash.status_code == 409 and clash.json()["code"] == "label_taken"
    assert next(c for c in listed(client).connections if c.id == sams.id).personal

"""Controls: the fake Gmail refuses what Gmail refuses and records what a write put in the mailbox, exercised at its own
HTTP boundary with no `ashley` code between, so a green result from it means something."""

import asyncio
from email.message import EmailMessage
from typing import Any

import httpx2
import pytest
from mail_changes_blind_fake_support import FakeGmail, b64
from mail_changes_blind_support import day, message

API = "https://gmail.googleapis.com/gmail/v1/users/me"


def call(fake: FakeGmail, method: str, path: str, token: str = "good", body: dict[str, Any] | None = None) -> httpx2.Response:
    async def go() -> httpx2.Response:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(fake.handle)) as http:
            return await http.request(method, API + path, json=body, headers={"authorization": f"Bearer {token}"})

    return asyncio.run(go())


def stocked(may_write: bool = True) -> FakeGmail:
    fake = FakeGmail()
    fake.accept("good", "rt", may_write)
    fake.add(message("m1", day(3, 1), "Trip", labels=["INBOX", "UNREAD"]), message("m2", day(3, 2), "Menu"))
    return fake


def raw(to: str = "a@x.test", subject: str = "Hi", body: str = "text", **headers: str) -> str:
    mail = EmailMessage()
    mail["To"], mail["Subject"] = to, subject
    for k, v in headers.items():
        mail[k.replace("_", "-")] = v
    mail.set_content(body)
    return b64(mail.as_string()).rstrip("=")


def test_a_write_with_a_token_that_may_not_write_is_403_and_changes_nothing() -> None:
    fake = stocked(may_write=False)
    assert call(fake, "POST", "/messages/send", body={"raw": raw()}).status_code == 403
    assert call(fake, "POST", "/messages/m1/modify", body={"addLabelIds": ["TRASH"]}).status_code == 403
    assert fake.sent == [] and fake.labels_of("m1") == {"INBOX", "UNREAD"}


def test_an_unknown_token_is_401_in_gmails_error_shape() -> None:
    fake = stocked()
    refused = call(fake, "POST", "/messages/send", "nope", {"raw": raw()})
    assert refused.status_code == 401 and refused.json()["error"]["status"] == "UNAUTHENTICATED"


def test_a_send_is_read_back_from_its_raw_bytes() -> None:
    fake = stocked()
    sent = call(fake, "POST", "/messages/send", body={"raw": raw("a@x.test, b@y.test", "Héllo", "café", In_Reply_To="<m1@mail.test>"),
                                                      "threadId": "th-m1"})
    assert sent.status_code == 200 and sent.json()["labelIds"] == ["SENT"] and sent.json()["threadId"] == "th-m1"
    one = fake.sent[0]
    assert one.to == ("a@x.test", "b@y.test") and one.subject == "Héllo" and one.body == "café"
    assert one.in_reply_to == "<m1@mail.test>" and one.thread_id == "th-m1" and one.bcc == ()


def test_a_draft_is_stored_and_not_sent() -> None:
    fake = stocked()
    made = call(fake, "POST", "/drafts", body={"message": {"raw": raw()}})
    assert made.status_code == 200 and made.json()["message"]["labelIds"] == ["DRAFT"]
    assert len(fake.drafts) == 1 and fake.sent == []


def test_a_send_with_no_raw_is_400() -> None:
    assert call(stocked(), "POST", "/messages/send", body={}).status_code == 400


def test_modify_adds_and_removes_and_an_unknown_label_id_is_400_with_no_change() -> None:
    fake = stocked()
    assert call(fake, "POST", "/messages/m1/modify", body={"addLabelIds": ["Label_12"], "removeLabelIds": ["UNREAD"]}).status_code == 200
    assert fake.labels_of("m1") == {"INBOX", "Label_12"}
    assert call(fake, "POST", "/messages/m1/modify", body={"addLabelIds": ["Label_99"]}).status_code == 400
    assert fake.labels_of("m1") == {"INBOX", "Label_12"}


def test_batch_modify_is_all_or_nothing_for_an_unknown_id() -> None:
    fake = stocked()
    bad = call(fake, "POST", "/messages/batchModify", body={"ids": ["m1", "ghost"], "addLabelIds": ["Label_12"]})
    assert bad.status_code == 404 and fake.labels_of("m1") == {"INBOX", "UNREAD"}
    assert call(fake, "POST", "/messages/batchModify", body={"ids": ["m1", "m2"], "addLabelIds": ["Label_12"]}).status_code == 200
    assert "Label_12" in fake.labels_of("m1") and "Label_12" in fake.labels_of("m2")


def test_trash_moves_out_of_the_inbox_and_untrash_back() -> None:
    fake = stocked()
    call(fake, "POST", "/messages/m1/trash")
    assert fake.labels_of("m1") == {"UNREAD", "TRASH"}
    call(fake, "POST", "/messages/m1/untrash")
    assert fake.labels_of("m1") == {"UNREAD", "INBOX"}


@pytest.mark.parametrize(("method", "path"), [("DELETE", "/messages/m1"), ("POST", "/messages/batchDelete"),
                                              ("POST", "/labels"), ("DELETE", "/drafts/r-1")])
def test_deletion_and_label_creation_are_forbidden_and_recorded(method: str, path: str) -> None:
    fake = stocked()
    assert call(fake, method, path, body={"ids": ["m1"], "name": "x"}).status_code == 403
    assert len(fake.forbidden) == 1 and {m.id for m in fake.messages} == {"m1", "m2"}


def test_reads_are_served_and_a_trashed_message_is_not_listed() -> None:
    fake = stocked()
    call(fake, "POST", "/messages/m2/trash")
    assert [m["id"] for m in call(fake, "GET", "/messages").json()["messages"]] == ["m1"]
    assert call(fake, "GET", "/messages/m2?format=full").json()["payload"]["headers"][2]["value"] == "Menu"
    assert call(fake, "GET", "/messages/ghost").status_code == 404


def test_gmail_down_is_unreachable_and_a_status_fails_writes_only() -> None:
    fake = stocked()
    fake.gmail_status = 503
    assert call(fake, "GET", "/profile").status_code == 200
    assert call(fake, "POST", "/messages/send", body={"raw": raw()}).status_code == 503 and fake.sent == []
    fake.gmail_down = True
    with pytest.raises(httpx2.ConnectError):
        call(fake, "GET", "/profile")

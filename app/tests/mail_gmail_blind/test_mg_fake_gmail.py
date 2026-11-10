"""Controls: the fake Gmail the suite rests on refuses what Gmail refuses and filters as its search operators do, so a
green result from it means something. It is exercised at its own HTTP boundary, with no `ashley` code between."""

import asyncio
from datetime import UTC, datetime

import httpx2
from mail_gmail_blind_fake_support import CLIENT_ID, CLIENT_SECRET, FakeGmail, encoded
from mail_gmail_blind_support import day, message

API = "https://gmail.googleapis.com/gmail/v1/users/me"


def get(fake: FakeGmail, path: str, token: str = "good", **params: object) -> httpx2.Response:
    async def go() -> httpx2.Response:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(fake.handle)) as http:
            return await http.get(API + path, params={k: str(v) for k, v in params.items()},
                                  headers={"authorization": f"Bearer {token}"})

    return asyncio.run(go())


def refresh(fake: FakeGmail, token: str, secret: str = CLIENT_SECRET) -> httpx2.Response:
    async def go() -> httpx2.Response:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(fake.handle)) as http:
            return await http.post("https://oauth2.googleapis.com/token", data={
                "grant_type": "refresh_token", "refresh_token": token, "client_id": CLIENT_ID, "client_secret": secret})

    return asyncio.run(go())


def stocked() -> FakeGmail:
    fake = FakeGmail()
    fake.accept("good", "rt-good")
    fake.add(message("m1", day(3, 1), "Trip money", labels=("INBOX", "UNREAD", "Label_12"), text="bring ten dollars"),
             message("m2", day(3, 5), "Lunch menu", sender="Bob <bob@cafe.test>", attachments=(("menu.pdf", "application/pdf", 99),)),
             message("m3", day(3, 3), "Old news", labels=("Label_13",)),
             message("m4", day(3, 9), "Junk", labels=("SPAM",)))
    return fake


def ids(response: httpx2.Response) -> list[str]:
    return [m["id"] for m in response.json().get("messages", [])]


def test_an_unknown_or_expired_token_is_401_in_gmails_error_shape() -> None:
    fake = stocked()
    fake.expired.add("good")
    assert get(fake, "/profile", "nope").status_code == 401
    refused = get(fake, "/profile", "good")
    assert refused.status_code == 401 and refused.json()["error"]["status"] == "UNAUTHENTICATED"


def test_list_is_newest_first_without_spam_and_answers_ids_only() -> None:
    answer = get(stocked(), "/messages")
    assert ids(answer) == ["m2", "m3", "m1"]
    assert set(answer.json()["messages"][0]) == {"id", "threadId"}


def test_list_pages_by_token_and_omits_the_key_when_nothing_matches() -> None:
    fake = stocked()
    first = get(fake, "/messages", maxResults=2)
    assert ids(first) == ["m2", "m3"]
    second = get(fake, "/messages", maxResults=2, pageToken=first.json()["nextPageToken"])
    assert ids(second) == ["m1"] and "nextPageToken" not in second.json()
    empty = get(fake, "/messages", q="zebra")
    assert empty.status_code == 200 and "messages" not in empty.json()


def test_operators_filter() -> None:
    fake = stocked()
    assert ids(get(fake, "/messages", q="from:bob")) == ["m2"]
    assert ids(get(fake, "/messages", q='subject:"old news"')) == ["m3"]
    assert ids(get(fake, "/messages", q="subject:(trip money)")) == ["m1"]
    assert ids(get(fake, "/messages", q="is:unread")) == ["m1"]
    assert ids(get(fake, "/messages", q="has:attachment")) == ["m2"]
    assert ids(get(fake, "/messages", q="label:school")) == ["m1"]
    assert ids(get(fake, "/messages", q="after:2026/03/04")) == ["m2"]
    assert ids(get(fake, "/messages", q="before:2026-03-02")) == ["m1"]
    assert ids(get(fake, "/messages", q="ten dollars")) == ["m1"]
    assert ids(get(fake, "/messages", labelIds="Label_13")) == ["m3"]
    assert ids(get(fake, "/messages", q="in:spam", includeSpamTrash="true")) == ["m4"]


def test_an_operator_it_does_not_know_is_400_not_an_empty_list() -> None:
    assert get(stocked(), "/messages", q="larger:5M").status_code == 400


def test_metadata_has_only_the_headers_asked_for_and_no_parts_full_has_the_tree() -> None:
    fake = stocked()
    meta = get(fake, "/messages/m2", format="metadata", metadataHeaders="Subject").json()
    assert [h["name"] for h in meta["payload"]["headers"]] == ["Subject"] and "parts" not in meta["payload"]
    full = get(fake, "/messages/m2", format="full").json()
    assert [p["filename"] for p in full["payload"]["parts"] if p["filename"]] == ["menu.pdf"]
    assert get(fake, "/messages/nope").status_code == 404


def test_a_plain_message_is_one_part_with_its_body_inline() -> None:
    full = get(stocked(), "/messages/m1", format="full").json()
    assert full["payload"]["mimeType"] == "text/plain" and full["payload"]["body"]["data"]


def test_only_reads_are_served() -> None:
    async def go() -> int:
        fake = stocked()
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(fake.handle)) as http:
            return (await http.post(API + "/messages/m1/trash", headers={"authorization": "Bearer good"})).status_code

    assert asyncio.run(go()) == 405


def test_the_token_endpoint_refuses_a_bad_client_a_stranger_token_and_a_revoked_grant() -> None:
    fake = stocked()
    assert refresh(fake, "rt-good", "wrong").status_code == 401
    assert refresh(fake, "rt-unknown").json()["error"] == "invalid_grant"
    granted = refresh(fake, "rt-good")
    assert granted.status_code == 200 and granted.json()["access_token"] in fake.valid
    assert "refresh_token" not in granted.json()
    fake.refuse_refresh = True
    assert refresh(fake, "rt-good").json()["error"] == "invalid_grant"


def test_an_encoded_subject_is_an_rfc_2047_word() -> None:
    assert encoded("Café menu").startswith("=?utf-8?") and datetime(2026, 1, 1, tzinfo=UTC)

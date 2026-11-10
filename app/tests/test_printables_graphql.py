"""The Printables adapter over answers recorded from the real API: what it sends (every value as a variable), the records
it makes, how it fails, and that a download goes only to Printables' file hosts."""

import asyncio
import json

import httpx2
import pytest

from ashley import logs
from ashley.printables import graphql
from ashley.printables.printables import PrintablesFailed, model_id_of
from page_support import Resolver
from printables_support import CONFIG, STEP_FILE, STL_FILE, THREE_MF_FILE, adapter, api, file_bytes, link_of, recorded
from search_support import events, raising, serving

BIG = 25 * 1024 * 1024


def test_a_search_sends_its_text_as_a_variable_and_makes_models_of_what_came_back() -> None:
    fake = api(recorded())
    found = asyncio.run(adapter(fake).search('rsa" } mutation { x'))
    (request,) = fake.requests
    sent = json.loads(request.content)
    assert sent["query"] == graphql.SEARCH and "rsa" not in sent["query"]
    assert sent["variables"] == {"q": 'rsa" } mutation { x', "n": CONFIG.results}
    first = found[0]
    assert (first.id, first.name, first.author) == ("100001", "DESK PENCIL CUP", "MakerOne")
    assert (first.likes, first.downloads, first.makes, first.rating) == (45, 683, 7, 5.0)
    assert first.url == "https://www.printables.com/model/100001-desk-pencil-cup"
    assert [(f.id, f.name, f.size) for f in first.files] == [("200001", "cup_v3.stl", 335384)]
    assert [m.id for m in found] == ["100001", "100002", "100003", "100004", "100005"]
    assert found[1].rating == 4.7 and len(found[1].files) == 4


def test_a_search_with_no_hits_is_an_empty_list() -> None:
    assert asyncio.run(adapter(api({"search": recorded()["search-none"]})).search("zzzxqqqnothing")) == []


def test_a_models_detail_has_its_description_license_category_and_date() -> None:
    detail = asyncio.run(adapter(api(recorded())).detail("100002"))
    assert detail.model.name == "Pencil Cup & Note Holder" and len(detail.model.files) == 4
    assert detail.description.startswith("<p>This is a remixed model") and detail.category == "Office"
    assert detail.license.startswith("Creative Commons") and detail.published == "2024-06-19"


def test_a_model_that_does_not_exist_is_not_found() -> None:
    with pytest.raises(PrintablesFailed) as failed:
        asyncio.run(adapter(api(recorded())).detail("1"))
    assert failed.value.reason == "not_found"


@pytest.mark.parametrize("bad", ["", "12a", "1 2", "../1", "١٢"])
def test_an_id_that_is_not_digits_never_reaches_the_api(bad: str) -> None:
    fake = api(recorded())
    with pytest.raises(PrintablesFailed):
        asyncio.run(adapter(fake).detail(bad))
    assert fake.requests == []


@pytest.mark.parametrize(("file", "name", "model"), [(STL_FILE, "keychain.stl", "100101"),
                                                      (THREE_MF_FILE, "peg.3mf", "100201"),
                                                      (STEP_FILE, "washer.stp", "100301")])
def test_a_download_is_the_recorded_files_bytes_from_the_address_printables_gave(file: str, name: str,
                                                                                model: str) -> None:
    fake = api(recorded())
    data = asyncio.run(adapter(fake).download(model, file, BIG))
    assert data == file_bytes(name)
    asked = json.loads(fake.requests[0].content)
    assert asked["query"] == graphql.LINK and asked["variables"] == {"model": model, "file": file}
    assert str(fake.requests[1].url) == link_of(file)


def test_a_file_printables_will_not_hand_over_needs_a_login_and_is_never_fetched() -> None:
    fake = api(recorded())
    with pytest.raises(PrintablesFailed) as failed:
        asyncio.run(adapter(fake).download("100001", "999999999", BIG))
    assert failed.value.reason == "needs_login" and len(fake.requests) == 1


def test_a_file_over_the_limit_is_too_large_and_none_of_it_is_kept() -> None:
    with pytest.raises(PrintablesFailed) as failed:
        asyncio.run(adapter(api(recorded())).download("100201", THREE_MF_FILE, 500))
    assert failed.value.reason == "too_large"


@pytest.mark.parametrize("link", ["https://evil.example/a.stl", "https://files.printables.com.evil.example/a.stl",
                                  "http://files.printables.com/a.stl", "https://127.0.0.1/a.stl",
                                  "https://api.printables.com/a.stl"])
def test_a_link_off_printables_file_hosts_is_never_fetched(link: str) -> None:
    answers = recorded()
    answers[f"link-{STL_FILE}"]["data"]["getDownloadLink"]["output"]["link"] = link
    fake = api(answers)
    with pytest.raises(PrintablesFailed) as failed:
        asyncio.run(adapter(fake).download("100101", STL_FILE, BIG))
    assert failed.value.reason == "unexpected" and len(fake.requests) == 1


def test_a_redirect_off_the_file_hosts_or_to_a_private_address_is_refused() -> None:
    off = httpx2.Response(302, headers={"location": "https://evil.example/a.stl"})
    fake = api(recorded(), {link_of(STL_FILE): off})
    with pytest.raises(PrintablesFailed) as failed:
        asyncio.run(adapter(fake).download("100101", STL_FILE, BIG))
    assert failed.value.reason == "unexpected" and len(fake.requests) == 2
    inside = httpx2.Response(302, headers={"location": "https://files.printables.com/other"})
    resolver = Resolver({"files.printables.com": ["10.0.0.8"]})
    with pytest.raises(PrintablesFailed):
        asyncio.run(adapter(api(recorded(), {link_of(STL_FILE): inside}), resolver).download("100101", STL_FILE, BIG))


def test_an_api_that_does_not_answer_or_answers_something_else_is_a_failure_that_says_which() -> None:
    for fake, reason in ((raising(httpx2.ConnectError("down")), "unreachable"), (serving({}, 503), "unreachable"),
                         (serving({"html": "challenge"}), "unexpected"), (serving({"data": None}), "unexpected")):
        with pytest.raises(PrintablesFailed) as failed:
            asyncio.run(adapter(fake).search("x"))
        assert failed.value.reason == reason


def test_the_log_has_the_call_the_outcome_and_the_count_and_nothing_a_person_wrote(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    asyncio.run(adapter(api(recorded())).search("a secret query"))
    out = capsys.readouterr().out
    (line,) = events(out, "printables.call")
    assert (line["call"], line["outcome"], line["count"]) == ("search", "ok", "5")
    assert "secret" not in out and "RSA" not in out


@pytest.mark.parametrize(("url", "found"), [
    ("https://www.printables.com/model/100001-desk-pencil-cup", "100001"),
    ("https://www.printables.com/model/100001", "100001"),
    ("https://printables.com/en/model/100001-x/", "100001"),
    ("https://www.printables.com/model/100001-x/comments", None),
    ("http://www.printables.com/model/100001-x", None),
    ("https://www.printables.com.evil.example/model/100001-x", None),
    ("https://evil.example/www.printables.com/model/100001-x", None),
    ("https://www.printables.com/@someone", None)])
def test_a_model_page_is_told_by_its_parsed_host_and_path(url: str, found: str | None) -> None:
    assert model_id_of(url) == found

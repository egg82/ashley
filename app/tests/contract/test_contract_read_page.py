"""`read_page`, inside the look-up: results numbered across the whole look-up and fresh in the next, the tool offered to
the sub-agent only, the model naming a number and never a URL, every argument and number error, the two-page limit, the
request a read makes, and the text's cut to `page_chars`."""

import json
from typing import Any

import pytest
from ashley.inference.model import ToolCall
from ashley.tools.composite import CompositeTools
from read_page_contract_support import (CONFIG, NEEDS_NUMBER, NO_SUCH, SITES, TWO_READ, UA, Dns, Net, Rig, calls, cfg,
                                        fetch, finish, install_dns, ok_text, page, read, read_args, read_number, web)
from search_contract_support import run

OPEN = "<html><body><p>Open 9-5</p></body></html>"


@pytest.fixture(autouse=True)
def dns(monkeypatch: pytest.MonkeyPatch) -> Dns:
    return install_dns(monkeypatch)


def second_sites() -> list[str]:
    return [f"https://site{i}.test/page{i}" for i in range(11, 19)]


def two_searches() -> Net:
    return Net(urls={"second": second_sites()}, pages={f"site{i}.test": page(OPEN) for i in range(1, 20)})


def test_search_results_are_numbered_from_one_in_order_and_keep_their_fields() -> None:
    out = Rig(two_searches()).look_up([calls(web()), finish()])
    (first,) = out.searches()
    results = json.loads(first.content)["results"]
    assert [r["result"] for r in results] == [1, 2, 3, 4, 5]
    assert all(type(r["result"]) is int for r in results)
    assert all({"title", "snippet", "source"} <= set(r) for r in results)


def test_a_second_search_continues_the_numbering_and_does_not_restart() -> None:
    net = two_searches()
    out = Rig(net).look_up([calls(web()), calls(web("second")), calls(read_number(7), read_number(2)), finish()])
    first, second = (json.loads(s.content)["results"] for s in out.searches())
    assert [r["result"] for r in first] == [1, 2, 3, 4, 5] and [r["result"] for r in second] == [6, 7, 8, 9, 10]
    assert net.hosts == ["site12.test", "site2.test"], "7 is the second search's second result; 2 the first's"
    assert [json.loads(p.content)["result"] for p in out.pages] == [7, 2]


def test_two_searches_in_one_round_are_numbered_in_the_order_asked() -> None:
    out = Rig(two_searches()).look_up([calls(web("second"), web()), finish()])
    second, first = (json.loads(s.content)["results"] for s in out.searches())
    assert [r["result"] for r in second] == [1, 2, 3, 4, 5] and [r["result"] for r in first] == [6, 7, 8, 9, 10]


def test_the_next_look_up_numbers_afresh_and_cannot_read_the_last_ones() -> None:
    net = two_searches()
    rig = Rig(net)
    before = rig.look_up([calls(web()), calls(web("second")), calls(read_number(7)), finish()])
    assert net.hosts == ["site12.test"], "control: 7 was a result of the first look-up"
    after = rig.look_up([calls(web()), calls(read_number(7), read_number(1)), finish()])
    (search,) = after.searches()
    assert [r["result"] for r in json.loads(search.content)["results"]] == [1, 2, 3, 4, 5]
    bad, good = after.brain.reads()
    assert bad[1].content == NO_SUCH and bad[1].is_error and good[1].is_error is False
    assert net.hosts == ["site12.test", "site1.test"] and before.result.is_error is False


@pytest.mark.parametrize("number", [-1, 6, 8, 999])
def test_a_number_the_look_up_never_returned_is_an_error_and_fetches_nothing(number: int) -> None:
    net = two_searches()
    out = Rig(net).look_up([calls(web()), calls(read_number(number)), finish()])
    ((asked, result),) = out.brain.reads()
    assert (result.call_id, result.content, result.is_error) == (asked.id, NO_SUCH, True)
    assert net.hits == [], "the captured search had 8 results; only 5 were returned"


def test_a_read_before_any_search_is_the_same_error() -> None:
    net = two_searches()
    out = Rig(net).look_up([calls(read_number(1)), finish()])
    assert out.pages[0].content == NO_SUCH and out.pages[0].is_error and net.hits == []


@pytest.mark.parametrize("arguments", [{}, {"result": None}, {"result": "1"}, {"result": 1.5}, {"result": [1]},
                                       {"result": {"n": 1}}, {"url": SITES[0]}, {"query": "x"}])
def test_a_missing_or_non_integer_result_is_an_error_and_fetches_nothing(arguments: dict[str, object]) -> None:
    net = two_searches()
    out = Rig(net).look_up([calls(web()), calls(read_args(arguments)), finish()])
    ((asked, result),) = out.brain.reads()
    assert (result.call_id, result.content, result.is_error) == (asked.id, NEEDS_NUMBER, True)
    assert net.hits == []


def test_a_good_number_is_not_an_argument_error() -> None:
    net = two_searches()
    out = Rig(net).look_up([calls(web()), calls(read_args({"result": 1})), finish()])
    assert out.pages[0].is_error is False and net.hosts == ["site1.test"], "control for the argument errors"


def test_a_url_beside_the_number_is_never_fetched_or_resolved(dns: Dns) -> None:
    net = two_searches()
    out = Rig(net).look_up([calls(web()), calls(read_args({"result": 2, "url": "https://evil.test/x"})), finish()])
    assert out.pages[0].is_error is False
    assert net.hosts == ["site2.test"] and "evil.test" not in dns.asked


def test_read_page_is_offered_to_the_sub_agent_on_every_step_beside_the_search_tools() -> None:
    out = Rig(two_searches()).look_up([calls(web()), calls(read(0, 0)), finish()])
    assert len(out.brain.seen) == 3
    for step in out.brain.seen:
        assert [t.name for t in step.prompt.tools if t.name == "read_page"] == ["read_page"]
        assert {"search_web", "find_places"} <= {t.name for t in step.prompt.tools}
    (tool,) = [t for t in out.brain.seen[0].prompt.tools if t.name == "read_page"]
    properties: Any = tool.parameters["properties"]
    assert tool.parameters["type"] == "object" and tool.parameters["required"] == ["result"]
    assert set(properties) == {"result"} and properties["result"]["type"] == "integer"
    assert "result" in tool.description.lower() and "search_web" in tool.description


def test_ashleys_catalogue_still_has_only_look_up_and_cannot_call_read_page() -> None:
    net = two_searches()
    rig = Rig(net)
    (tool,) = run(rig.tools.catalogue()).specs
    assert tool.name == "look_up"
    top = run(CompositeTools({"search": rig.tools}).catalogue())
    assert [t.name for t in top.specs] == ["look_up"]
    result = run(rig.tools.call(ToolCall("x1", "read_page", {"result": 1})))
    assert result.is_error and result.call_id == "x1" and net.hits == []


def test_a_search_a_page_and_an_answer_fit_the_shipped_three_rounds() -> None:
    rig = Rig(two_searches(), cfg(max_rounds=3))
    out = rig.look_up([calls(web()), calls(read(0, 0)), finish("Open 9-5.")])
    assert json.loads(out.result.content)["found"] is True and not out.result.is_error
    out = rig.look_up([calls(web()), calls(read(0, 0)), calls(read(0, 1)), finish("Open 9-5.")])
    assert json.loads(out.result.content)["answer"] == "Open 9-5.", "two pages, answered under tool choice none"
    assert [s.prompt.tool_choice for s in out.brain.seen] == ["auto", "auto", "auto", "none"]


def test_the_third_read_is_refused_and_fetches_nothing() -> None:
    net = two_searches()
    plan = [calls(web()), calls(read(0, 0)), calls(read(0, 1)), calls(read(0, 2)), finish()]
    out = Rig(net, cfg(max_rounds=5)).look_up(plan)
    (a, _), (b, _), (c, third) = out.brain.reads()
    assert [r.is_error for r in out.pages] == [False, False, True]
    assert (third.call_id, third.content) == (c.id, TWO_READ) and a.id != b.id
    assert net.hosts == ["site1.test", "site2.test"]


def test_the_third_read_in_one_round_is_refused_too() -> None:
    net = two_searches()
    out = Rig(net).look_up([calls(web()), calls(read(0, 0), read(0, 1), read(0, 2)), finish()])
    assert [(r.is_error, r.content == TWO_READ) for r in out.pages] == [(False, False), (False, False), (True, True)]
    assert net.hosts == ["site1.test", "site2.test"]


def test_the_limit_is_per_look_up_not_per_tools_object() -> None:
    net = two_searches()
    rig = Rig(net)
    for _ in range(2):
        out = rig.look_up([calls(web()), calls(read(0, 0), read(0, 1), read(0, 2)), finish()])
        assert [r.is_error for r in out.pages] == [False, False, True]
    assert net.hosts == ["site1.test", "site2.test"] * 2


def test_a_read_is_an_https_get_of_the_results_url_with_the_shared_user_agent_and_timeout() -> None:
    result, net = fetch(page(OPEN), config=cfg(page_timeout_s=2.5))
    (request,) = net.hits
    assert request.method == "GET" and str(request.url) == SITES[0]
    assert request.headers["user-agent"] == UA
    assert request.extensions["timeout"]["read"] == 2.5 and request.extensions["timeout"]["connect"] == 2.5
    body = json.loads(result.content)
    assert body["result"] == 1 and ok_text(result).strip() == "Open 9-5"


def test_a_page_is_cut_to_page_chars_and_a_shorter_one_is_not() -> None:
    text = ok_text(fetch(page("x" * 5000, ctype="text/plain"), config=cfg(page_chars=1000))[0])
    assert text.strip() == "x" * 1000
    exact = ok_text(fetch(page("x" * 1000, ctype="text/plain"), config=cfg(page_chars=1000))[0])
    assert exact.strip() == "x" * 1000
    assert ok_text(fetch(page("x" * 800, ctype="text/plain"), config=cfg(page_chars=1000))[0]).strip() == "x" * 800
    html = ok_text(fetch(page("<p>" + "y" * 5000 + "</p>"), config=cfg(page_chars=1000))[0])
    assert 900 < len(html) <= 1000 and set(html.strip()) == {"y"}


def test_the_shipped_page_chars_apply_when_the_page_is_longer() -> None:
    text = ok_text(fetch(page("w" * 9000, ctype="text/plain"))[0])
    assert text.strip() == "w" * CONFIG.page_chars

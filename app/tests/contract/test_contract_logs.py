"""Access log and logfmt contract: one `key=value` line per request, nothing identifying, health unlogged."""

import re

import pytest
from ashley import logs
from contract_support import client, down_client
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from logging import getLogger

REQUEST = re.compile(r"(?:^| )event=http\.request(?: |$)")
FIELD = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S*)')


def request_lines(out: str) -> list[dict[str, str]]:
    return [dict(FIELD.findall(line)) for line in out.splitlines() if REQUEST.search(line)]


def test_a_request_is_one_line_with_method_route_status_and_duration(
    empty_database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    logs.setup()
    with client(empty_database) as c:
        capsys.readouterr()
        assert c.get("/api/ready").status_code == 200
    lines = request_lines(capsys.readouterr().out)
    assert len(lines) == 1
    line = lines[0]
    assert (line["method"], line["route"], line["status"]) == ("GET", "/api/ready", "200")
    assert float(line["ms"]) >= 0


def test_a_failing_request_logs_its_real_status(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    with down_client("canarypw") as c:
        capsys.readouterr()
        assert c.get("/api/ready").status_code == 503
    out = capsys.readouterr().out
    assert [ln["status"] for ln in request_lines(out)] == ["503"]
    assert "canarypw" not in out


def test_health_is_not_logged(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    with down_client() as c:
        capsys.readouterr()
        for _ in range(3):
            assert c.get("/api/health").status_code == 200
        c.get("/api/ready")
    out = capsys.readouterr().out
    assert request_lines(out), "control: the ready request must have been logged"
    assert "/api/health" not in out


TOKEN = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=8, max_size=24).map(lambda s: "zq" + s)


def test_no_query_string_header_value_or_client_address_is_ever_logged(
    empty_database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    logs.setup()

    @settings(max_examples=25, deadline=None)
    @given(query=TOKEN, header=TOKEN, cookie=TOKEN)
    def law(query: str, header: str, cookie: str) -> None:
        capsys.readouterr()
        r = c.get(
            f"/api/ready?secret={query}&other={query}",
            headers={"X-Canary": header, "Authorization": f"Bearer {header}", "Cookie": f"s={cookie}"},
        )
        out = capsys.readouterr().out
        assert r.status_code == 200
        assert len(request_lines(out)) == 1, "control: the request was logged"
        for leaked in (query, header, cookie, "203.0.113.77", "secret=", "Bearer"):
            assert leaked not in out

    with client(empty_database, client=("203.0.113.77", 4242)) as c:
        law()


def test_an_unknown_route_is_logged_once_without_its_query_string(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    with down_client() as c:
        capsys.readouterr()
        assert c.get("/api/nope?zqsecret=1").status_code == 404
    out = capsys.readouterr().out
    assert [ln["status"] for ln in request_lines(out)] == ["404"]
    assert "zqsecret" not in out


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(value=st.text(alphabet=st.sampled_from(["a", "b", " ", "\n", "\r", '"', "\\", "=", "\t"]), max_size=40))
def test_any_field_value_still_makes_exactly_one_line(value: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    logs.info(getLogger("ashley.contract"), "contract.probe", note=value, n=3)
    out = capsys.readouterr().out
    assert out.endswith("\n") and out.count("\n") == 1, repr(out)
    assert "event=contract.probe" in out


def test_an_exception_is_logged_by_type_and_frames_never_by_message(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    try:
        raise ValueError("zqROWDATA")
    except ValueError:
        logs.error(getLogger("ashley.contract"), "contract.failed", exc=True)
    out = capsys.readouterr().out
    assert "ValueError" in out
    assert "zqROWDATA" not in out
    assert out.count("\n") == 1


def test_an_unmatched_path_is_not_logged_as_a_route(capsys: pytest.CaptureFixture[str]) -> None:
    """The access line carries the route template; a request that matches no route has none, so its raw path (which
    could hold an id) is not written."""
    logs.setup()
    with down_client() as c:
        capsys.readouterr()
        assert c.get("/api/users/zq4815162342").status_code == 404
    out = capsys.readouterr().out
    assert len(request_lines(out)) == 1
    assert "zq4815162342" not in out

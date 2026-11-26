"""The nightly CI readout (tools/ci_health.py) over one real day of pull-request runs (`ci_health_captured/`, captured
from `gh` with only the fields it reads): it names the tests whose first attempt failed in runs that passed on rerun,
reads a test failed at teardown from its ERROR line, says so when a rerun's log names no test, compares the day's wall
clock with the budget, and keeps one issue per problem, updating an open one rather than opening another."""
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from tools import ci_health

DAY = json.loads((Path(__file__).parent / "ci_health_captured" / "2026-11-21.json").read_text())
NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)
TESTS = re.compile(r"^tests\b")


class FakeGh:
    """`gh` serving the captured day; issue writes are recorded, and `open_issues` is what `issue list` finds."""

    def __init__(self, runs: list[dict[str, Any]], open_issues: dict[str, int] | None = None) -> None:
        self.runs, self.open_issues = runs, open_issues or {}
        self.writes: list[list[str]] = []

    def __call__(self, args: list[str]) -> str:
        if args[0] == "api":
            return self.api(args[-1] if args[1] == "--allow-escape-sequences" else args[3])
        if args[:2] == ["issue", "list"]:
            label = args[args.index("--label") + 1].removeprefix("ci-health-")
            return json.dumps([{"number": self.open_issues[label]}] if label in self.open_issues else [])
        self.writes.append(args)
        return "https://github.com/OWNER/NAME/issues/301\n" if args[:2] == ["issue", "create"] else ""

    def api(self, path: str) -> str:
        if path == "repos/OWNER/NAME/actions/runs":
            return "\n".join(json.dumps(r) for r in self.runs)
        if m := re.fullmatch(r"repos/OWNER/NAME/actions/runs/(\d+)/attempts/1/jobs", path):
            return "\n".join(json.dumps(j) for j in DAY["jobs"][m[1]])
        if m := re.fullmatch(r"repos/OWNER/NAME/actions/jobs/(\d+)/logs", path):
            return DAY["logs"][m[1]]
        raise AssertionError(f"not captured: {path}")


def readout(gh: FakeGh, budget: float, capsys: pytest.CaptureFixture[str], dry: bool = False) -> str:
    assert ci_health.run(ci_health.GitHub("OWNER/NAME", gh), budget, 1, "CI", TESTS, dry, NOW) == 0
    return capsys.readouterr().out


def bodies(gh: FakeGh, verb: str) -> dict[str, str]:
    """Each issue `create` or `edit` call's body, keyed by its title."""
    calls = [a for a in gh.writes if a[:2] == ["issue", verb]]
    return {a[a.index("--title") + 1]: a[a.index("--body") + 1] for a in calls}


def test_a_rerun_names_the_test_its_first_attempt_failed_and_an_infra_failure_says_no_test(
        capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(DAY["runs"])
    out = readout(gh, 60, capsys)
    body = bodies(gh, "create")[ci_health.KINDS["reruns"]]
    assert "`tests/test_watches_ha_entity.py::test_a_dropped_socket_is_subscribed_again_and_the_change_made_meanwhile" \
           "_wakes_her`" in body
    assert "`tests/test_watch_session_lease.py::test_of_two_sites_one_checks_and_the_other_takes_over_from_the_stored" \
           "_state`" in body
    assert body.count("no test id in the log") == 2, body   # two first attempts failed logging in to the registry
    assert body.count("- https://github.com/OWNER/NAME/actions/runs/") == 4, body
    assert ["label", "create", "ci-health-reruns"] == gh.writes[0][:3]
    assert "reruns_passed=4" in out and "issues=reruns created #301" in out, out


def test_an_open_issue_is_updated_never_duplicated(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(DAY["runs"], {"reruns": 245})
    out = readout(gh, 60, capsys)
    assert not bodies(gh, "create") and list(bodies(gh, "edit")) == [ci_health.KINDS["reruns"]]
    assert [a[2] for a in gh.writes if a[:2] == ["issue", "edit"]] == ["245"]
    assert "issues=reruns updated #245" in out, out


def test_a_median_over_the_budget_opens_an_issue_naming_the_slowest_run(capsys: pytest.CaptureFixture[str]) -> None:
    passed = [r for r in DAY["runs"] if r["conclusion"] == "success"]
    wall = {r["html_url"]: (datetime.fromisoformat(r["updated_at"]) - datetime.fromisoformat(r["created_at"]))
            .total_seconds() / 60 for r in passed}
    median = statistics.median(wall.values())
    gh = FakeGh(DAY["runs"])
    out = readout(gh, median - 0.5, capsys)
    body = bodies(gh, "create")[ci_health.KINDS["budget"]]
    assert f"median {median:.1f} min" in body and max(wall, key=wall.__getitem__) in body, body
    assert f"pr_runs={len(passed)}" in out and f"median_min={median:.1f}" in out, out
    gh = FakeGh(DAY["runs"])
    readout(gh, median + 0.5, capsys)
    assert ci_health.KINDS["budget"] not in bodies(gh, "create")


def test_a_day_with_no_rerun_and_under_budget_writes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh([r for r in DAY["runs"] if r["run_attempt"] == 1])
    out = readout(gh, 60, capsys)
    assert gh.writes == [] and "reruns_passed=0" in out and "issues=none" in out, out


def test_a_test_failed_at_teardown_is_named_from_its_error_line() -> None:
    """pytest reports a teardown failure, the per-test time ceiling's among them, as ERROR and never FAILED: a real
    shard's summary where the ceiling failed nine tests and nothing else did."""
    log = (Path(__file__).parent / "ci_health_captured" / "time-gate-errors.log").read_text()
    ids = ci_health.failing_tests(log)
    assert len(ids) == 9 and "FAILED" not in log, ids
    assert "tests/lexicon_household/test_lh_routes.py::test_a_household_at_the_limit_may_replace_but_not_add" in ids
    assert "tests/workshop_blind/test_route_contract.py::test_signed_out_is_401_on_every_route[GET-/api/benches-None]" \
        in ids


def test_a_dry_run_reports_but_writes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    gh = FakeGh(DAY["runs"])
    out = readout(gh, 1, capsys, dry=True)
    assert gh.writes == [] and "issues=budget dry-run;reruns dry-run" in out, out

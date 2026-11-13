"""The run on the wire: `RunApplied` and the bench's `last_run` carry the run's artifacts, with download links of the
files' kind for the run's own household, and the report with a verdict on each check."""

import time
from typing import Any
from urllib.parse import urlparse

from ashley.files.links import check, window_end
from run_artifacts_support import (CONFIG, GLB_NAME, GOOD, LINK_KEY, TYPES, Box, Rig, check_json, measurement, facts_body, model_output,
                                   part_json, rig, report_json, sha)

CHECKS = [check_json("fit", 2.0, ">=", 1.5, rests_on=["w"]), check_json("guess", 2.0, ">=", 1.5, rests_on=["g"]),
          check_json("miss", 2.0, ">=", 1.5, rests_on=["gone"]), check_json("bad", 1.0, ">=", 1.5, rests_on=["g"])]
REPORT = report_json(*CHECKS, parts=[part_json("lid")], triangles=48)


def measured_bench(r: Rig) -> tuple[int, int]:
    bench = r.new_bench()
    r.add(bench, "facts", facts_body(measurement("w", 30), measurement("g", 5, "guessed")))
    return bench, r.add(bench, "code", "box = 1")


def token_of(url: str) -> str:
    return urlparse(url).path.rsplit("/", 1)[1]


def by_name(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {i["name"]: i for i in items}


def test_a_model_run_returns_its_meshes_with_links_that_serve_the_bytes(db_url: str) -> None:
    with rig(db_url, Box([model_output(REPORT)])) as r:
        bench, piece = measured_bench(r)
        out = r.run_piece(bench, piece)["run_output"]
        got = by_name(out["artifacts"])
        assert set(got) == set(GOOD)
        for name, data in GOOD.items():
            one = got[name]
            assert (one["size_bytes"], one["media_type"]) == (len(data), TYPES[name])
            served = r.client.get(one["url"])
            assert served.status_code == 200 and served.content == data
            assert served.headers["content-type"].startswith(TYPES[name])
            grant = check(LINK_KEY.encode(), token_of(one["url"]), time.time())
            assert grant is not None and grant.sha256 == sha(data) and grant.household_id == r.homes[0]
            assert grant.media_type == TYPES[name] and grant.expires_at == one["expires_at"]


def test_a_link_reaches_only_the_household_that_made_the_run(db_url: str) -> None:
    with rig(db_url, Box([model_output(REPORT)])) as r:
        bench, piece = measured_bench(r)
        mine = by_name(r.run_piece(bench, piece)["run_output"]["artifacts"])
        r.as_("zed")
        zbench, zpiece = measured_bench(r)
        theirs = by_name(r.run_piece(zbench, zpiece)["run_output"]["artifacts"])
        for name in GOOD:
            a = check(LINK_KEY.encode(), token_of(mine[name]["url"]), time.time())
            z = check(LINK_KEY.encode(), token_of(theirs[name]["url"]), time.time())
            assert a is not None and z is not None
            assert (a.household_id, z.household_id) == r.homes and a.sha256 == z.sha256
            assert mine[name]["url"] != theirs[name]["url"]


def test_the_report_carries_the_numbers_and_a_verdict_on_each_check(db_url: str) -> None:
    with rig(db_url, Box([model_output(REPORT)])) as r:
        bench, piece = measured_bench(r)
        report = r.run_piece(bench, piece)["run_output"]["report"]
        assert report["triangles"] == 48
        [part] = report["parts"]
        assert (part["name"], part["volume"], part["bbox_min"], part["bbox_max"]) == (
            "lid", 6000.0, [0.0, 0.0, 0.0], [20.0, 30.0, 10.0])
        verdicts = {c["name"]: c["verdict"] for c in report["checks"]}
        assert verdicts == {"fit": "pass", "guess": "unconfirmed", "miss": "unconfirmed", "bad": "fail"}
        fit = by_name(report["checks"])["fit"]
        assert (fit["actual"], fit["op"], fit["target"], fit["tolerance"], fit["rests_on"]) == (2.0, ">=", 1.5, 0.0, ["w"])


def test_the_bench_read_back_shows_the_same_run(db_url: str) -> None:
    with rig(db_url, Box([model_output(REPORT)])) as r:
        bench, piece = measured_bench(r)
        applied = r.run_piece(bench, piece)
        pieces = {p["id"]: p for p in r.bench(bench)["pieces"]}
        last = pieces[piece]["last_run"]
        assert last["run_id"] == applied["run_id"]
        assert last["run_output"]["report"] == applied["run_output"]["report"]
        assert last["run_output"]["artifacts"] == applied["run_output"]["artifacts"]


def test_a_run_with_no_meshes_or_report_shows_neither(db_url: str) -> None:
    with rig(db_url, Box([model_output(None, {})])) as r:
        bench, piece = measured_bench(r)
        out = r.run_piece(bench, piece)["run_output"]
        assert out["artifacts"] == [] and out["report"] is None


def test_a_run_that_failed_has_no_report_even_if_it_left_one(db_url: str) -> None:
    with rig(db_url, Box([model_output(REPORT, exit_code=1)])) as r:
        bench, piece = measured_bench(r)
        out = r.run_piece(bench, piece)["run_output"]
        assert out["report"] is None


def test_a_broken_report_shows_none(db_url: str) -> None:
    with rig(db_url, Box([model_output('{"unit": "mm"}')])) as r:
        bench, piece = measured_bench(r)
        assert r.run_piece(bench, piece)["run_output"]["report"] is None


def test_a_process_with_no_link_key_lists_the_meshes_without_links(db_url: str) -> None:
    with rig(db_url, Box([model_output(REPORT)]), link_key=None) as r:
        bench, piece = measured_bench(r)
        got = r.run_piece(bench, piece)["run_output"]["artifacts"]
        assert {a["name"] for a in got} == set(GOOD) and all(a["url"] is None and a["expires_at"] is None for a in got)


def test_a_link_ends_with_the_current_half_window_and_is_the_same_address_when_read_again(db_url: str) -> None:
    with rig(db_url, Box([model_output(REPORT)])) as r:
        bench, piece = measured_bench(r)
        before = time.time()
        applied = by_name(r.run_piece(bench, piece)["run_output"]["artifacts"])
        after = time.time()
        ttl = CONFIG.link_ttl_s
        for one in applied.values():
            assert one["expires_at"] in {window_end(before, ttl), window_end(after, ttl)}
            grant = check(LINK_KEY.encode(), token_of(one["url"]), time.time())
            assert grant is not None and grant.inline is False
        again = by_name(next(p for p in r.bench(bench)["pieces"] if p["id"] == piece)["last_run"]["run_output"]["artifacts"])
        if again[GLB_NAME]["expires_at"] == applied[GLB_NAME]["expires_at"]:
            assert again == applied


def test_the_report_of_a_run_is_judged_by_the_facts_it_started_with(db_url: str) -> None:
    with rig(db_url, Box([model_output(REPORT)])) as r:
        bench = r.new_bench()
        measures = r.add(bench, "facts", facts_body(measurement("w", 30), measurement("g", 5, "datasheet")))
        piece = r.add(bench, "code", "box = 1")
        first = r.run_piece(bench, piece)["run_output"]["report"]
        assert {c["name"]: c["verdict"] for c in first["checks"]}["guess"] == "pass"
        r.command(bench, {"type": "edit", "piece_id": measures, "base_version": 1, "title": "t",
                          "body": facts_body(measurement("w", 30), measurement("g", 5, "guessed"))})
        last = next(p for p in r.bench(bench)["pieces"] if p["id"] == piece)["last_run"]["run_output"]["report"]
        assert last == first
        second = r.run_piece(bench, piece)["run_output"]["report"]
        assert {c["name"]: c["verdict"] for c in second["checks"]}["guess"] == "unconfirmed"

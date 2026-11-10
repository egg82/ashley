"""The envelope's budget on binary files: read only for a language that has one, each inflated against what is left of
the total, so a forged line cannot expand past it; and the runner's line read back whole."""

import base64
import tracemalloc
from pathlib import Path

import pytest
from ashley.runs import config, envelope
from ashley.runs.model import Output
from run_artifacts_lines import line_of, noise, packed, packed_zeros, pod_line
from run_artifacts_support import GOOD, MF_NAME, STL_NAME, glb

CFG = config.load()
BUDGET = 1 << 20


def parsed(line: str, budget: int = BUDGET) -> Output | None:
    return envelope.parse(line + "\n", CFG, budget)


def carried(out: Output | None) -> dict[str, bytes]:
    return dict(out.artifacts) if out is not None else {}


def total(out: Output | None) -> int:
    return sum(len(v) for v in carried(out).values())


def test_the_runners_line_comes_back_as_the_files_the_pod_held(tmp_path: Path) -> None:
    out = parsed(pod_line(tmp_path, GOOD, stdout="made it"), 16 << 20)
    assert out is not None and out.stdout == "made it"
    assert carried(out) == GOOD


def test_a_language_with_no_budget_reads_no_binary_files(tmp_path: Path) -> None:
    line = line_of({"out/model.glb": packed(glb())}, stdout="text")
    for out in (parsed(line, 0), envelope.parse(line + "\n", CFG)):
        assert out is not None and out.stdout == "text" and carried(out) == {}


def test_two_files_that_together_fit_exactly_are_both_read() -> None:
    a, b = noise(BUDGET // 2, "a"), noise(BUDGET // 2, "b")
    out = parsed(line_of({"a.glb": packed(a), "b.glb": packed(b)}))
    assert carried(out) == {"a.glb": a, "b.glb": b}


def test_one_byte_over_the_total_is_not_read_whole() -> None:
    a, b = noise(BUDGET // 2, "a"), noise(BUDGET // 2 + 1, "b")
    out = parsed(line_of({"a.glb": packed(a), "b.glb": packed(b)}))
    assert total(out) <= BUDGET
    assert carried(out).get("b.glb") != b


def test_the_budget_is_the_total_of_all_files_not_each() -> None:
    parts = {f"{i}.stl": packed(b"\x00" * (BUDGET // 4)) for i in range(10)}
    out = parsed(line_of(parts))
    assert total(out) <= BUDGET


def test_a_file_that_expands_far_past_the_budget_is_refused_and_never_held_whole() -> None:
    bomb = packed_zeros(64 << 20)
    assert len(bomb) < BUDGET
    line = line_of({"bomb.glb": bomb})
    tracemalloc.start()
    try:
        out = parsed(line)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert total(out) <= BUDGET and "bomb.glb" not in carried(out)
    assert peak < 16 << 20


def test_a_bomb_after_a_good_file_leaves_the_total_inside_the_budget() -> None:
    out = parsed(line_of({"a.glb": packed(glb(b"ok")), "z.stl": packed_zeros(8 << 20)}))
    assert total(out) <= BUDGET and "z.stl" not in carried(out)


@pytest.mark.parametrize("held", ["!!! not base64 !!!", "AAAA", 5, None, ["x"], {"a": 1}])
def test_a_file_that_is_not_deflated_base64_is_not_taken(held: object) -> None:
    out = parsed(line_of({"bad.glb": held, "good.glb": packed(glb(b"ok"))}))
    assert "bad.glb" not in carried(out)


@pytest.mark.parametrize("name", ["evil.exe", "notes.txt", "model.glb.sh", "glb"])
def test_only_the_three_mesh_suffixes_are_taken(name: str) -> None:
    out = parsed(line_of({name: packed(b"x"), "ok.stl": packed(b"s")}))
    assert name not in carried(out)


def test_artifacts_that_are_not_a_mapping_are_not_taken() -> None:
    for held in ([["a.glb", "x"]], "text", 5):
        out = parsed(line_of(held))
        assert carried(out) == {}


def test_the_rest_of_the_line_is_read_as_before_with_artifacts_beside_it() -> None:
    out = parsed(line_of({"a.stl": packed(b"s")}, stdout="hello", exit_code=3))
    assert out is not None and (out.outcome, out.exit_code, out.stdout) == ("ran", 3, "hello")
    assert STL_NAME not in carried(out) and MF_NAME not in carried(out)


def test_a_stream_cut_short_is_not_taken() -> None:
    whole = base64.b64decode(packed(noise(5000)))
    cut = base64.b64encode(whole[: len(whole) // 2]).decode()
    out = parsed(line_of({"cut.glb": cut, "ok.stl": packed(b"s")}))
    assert "cut.glb" not in carried(out) and carried(out).get("ok.stl") == b"s"


def test_a_file_that_holds_nothing_is_not_taken_and_is_named() -> None:
    out = parsed(line_of({"empty.glb": packed(b"")}))
    assert out is not None and carried(out) == {} and "empty.glb" in out.skipped


@pytest.mark.parametrize("name", ["../up.glb", "/abs.glb", "a/../../up.stl"])
def test_a_name_that_climbs_out_or_is_absolute_is_not_taken(name: str) -> None:
    out = parsed(line_of({name: packed(b"x"), "ok/in.glb": packed(b"y")}))
    assert name not in carried(out) and carried(out).get("ok/in.glb") == b"y"


def test_what_is_refused_is_named_in_skipped() -> None:
    out = parsed(line_of({"bad.glb": "!!", "a.exe": packed(b"x"), "ok.stl": packed(b"s")}))
    assert out is not None and {"bad.glb", "a.exe"} <= set(out.skipped) and "ok.stl" not in out.skipped


def test_no_more_files_than_the_sandbox_takes_are_read() -> None:
    parts = {f"f{i:02}.stl": packed(bytes([i + 1])) for i in range(CFG.max_files + 4)}
    out = parsed(line_of(parts))
    assert len(carried(out)) == CFG.max_files

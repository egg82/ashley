"""`artifacts.keep`: a bench run's binary files judged by their bytes against the type their suffix says, stored under
their household, recorded with name, hash, size and type; a chat run keeps none; what the store cannot take is named."""

import logging
from dataclasses import replace

import pytest
from ashley import services
from ashley.files.intake import key_of
from ashley.files.store import ObjectStore
from ashley.runs.artifacts import keep
from ashley.runs.model import Artifact, BenchRun, NewRun, Output
from run_artifacts_support import (ASCII_STL, CONFIG, GLB_NAME, GOOD, MF_NAME, PNG, STL_NAME, TYPES, Site, fields_of, glb,
                                   glb_version, go, log_text, ran, sha, stl, stl_claiming, threemf, zipped)

HOME = 11


def bench_run(home: int = HOME) -> NewRun:
    return NewRun(home, None, None, None, "build123d", "box = 1", "", {}, BenchRun(5, 3, 1, 1))


def chat_run(home: int = HOME) -> NewRun:
    return NewRun(home, 7, 8, "call-1", "build123d", "box = 1", "", {})


async def kept(run: NewRun, data: dict[str, bytes], site: Site | None = None, skipped: tuple[str, ...] = ()) -> tuple[Output, tuple[Artifact, ...], Site]:
    store = site or Site()
    services.register(ObjectStore, store)
    output, artifacts = await keep(run, 41, ran(artifacts=dict(sorted(data.items())), skipped=skipped), CONFIG)
    return output, artifacts, store


def test_each_mesh_is_stored_under_its_household_and_recorded_by_its_bytes() -> None:
    async def scenario() -> None:
        output, artifacts, store = await kept(bench_run(), GOOD)
        assert {a.name: (a.sha256, a.size, a.media_type) for a in artifacts} == {
            n: (sha(d), len(d), TYPES[n]) for n, d in GOOD.items()}
        assert store.held == {key_of(HOME, sha(d)): d for d in GOOD.values()}
        assert dict(output.artifacts) == {} and output.skipped == ()

    go(scenario())


def test_the_rest_of_the_output_is_returned_as_it_was() -> None:
    async def scenario() -> None:
        services.register(ObjectStore, Site())
        given = Output("ran", 0, "OUT", "ERR", True, {"a.txt": "A"}, ("x.bin",), dict(GOOD))
        output, _ = await keep(bench_run(), 1, given, CONFIG)
        assert (output.outcome, output.exit_code, output.stdout, output.stderr, output.cut) == ("ran", 0, "OUT", "ERR", True)
        assert dict(output.files) == {"a.txt": "A"} and "x.bin" in output.skipped

    go(scenario())


def test_a_chat_run_keeps_nothing_and_does_not_touch_the_store() -> None:
    async def scenario() -> None:
        output, artifacts, store = await kept(chat_run(), GOOD)
        assert artifacts == () and store.held == {} and store.calls.log == []
        assert dict(output.artifacts) == {} and set(GOOD) <= set(output.skipped)

    go(scenario())


def test_a_run_with_no_artifacts_keeps_none() -> None:
    async def scenario() -> None:
        _, artifacts, store = await kept(bench_run(), {})
        assert artifacts == () and store.calls.log == []

    go(scenario())


WRONG: dict[str, tuple[str, bytes]] = {
    "a glb that is a binary stl": (GLB_NAME, stl(2)),
    "a glb of version 1": (GLB_NAME, glb_version(1)),
    "a glb that is a picture": (GLB_NAME, PNG),
    "a glb of plain text": (GLB_NAME, b"hello, not a mesh\n"),
    "a glb that is a 3mf": (GLB_NAME, threemf()),
    "a glb that is empty": (GLB_NAME, b""),
    "an ascii stl": (STL_NAME, ASCII_STL),
    "an stl with a stray byte": (STL_NAME, stl(2, extra=1)),
    "an stl cut short": (STL_NAME, stl(2)[:-1]),
    "an stl whose count is too high": (STL_NAME, stl_claiming(3, 2)),
    "an stl whose count is too low": (STL_NAME, stl_claiming(1, 2)),
    "an stl of no triangles": (STL_NAME, stl(0)),
    "an stl that is a glb": (STL_NAME, glb(b"x" * 20)),
    "an stl that is empty": (STL_NAME, b""),
    "an stl shorter than its header": (STL_NAME, b"\x00" * 82),
    "an stl one byte short of its count": (STL_NAME, b"\x00" * 83),
    "a 3mf that is a plain zip": (MF_NAME, zipped({"readme.txt": b"hi"})),
    "a 3mf whose model is in another folder": (MF_NAME, zipped({"x/3D/3dmodel.model": b"<m/>"})),
    "a 3mf whose model is named otherwise": (MF_NAME, zipped({"3D/other.model": b"<m/>"})),
    "a 3mf that only starts like a zip": (MF_NAME, b"PK\x03\x04" + b"garbage" * 5),
    "a 3mf that is a glb": (MF_NAME, glb()),
    "a 3mf of plain text": (MF_NAME, b"<model/>"),
}


@pytest.mark.parametrize("what", list(WRONG))
def test_a_file_that_is_not_what_its_suffix_says_is_named_and_not_kept(what: str) -> None:
    name, data = WRONG[what]

    async def scenario() -> None:
        output, artifacts, store = await kept(bench_run(), {name: data})
        assert artifacts == () and store.held == {}
        assert name in output.skipped

    go(scenario())


def test_a_wrong_file_does_not_stop_the_right_ones() -> None:
    async def scenario() -> None:
        output, artifacts, store = await kept(bench_run(), {GLB_NAME: PNG, STL_NAME: GOOD[STL_NAME], MF_NAME: GOOD[MF_NAME]})
        assert {a.name for a in artifacts} == {STL_NAME, MF_NAME}
        assert GLB_NAME in output.skipped and len(store.held) == 2

    go(scenario())


def test_the_smallest_binary_stl_and_a_plain_glb_header_are_taken() -> None:
    async def scenario() -> None:
        _, artifacts, _ = await kept(bench_run(), {STL_NAME: stl(1), GLB_NAME: glb()})
        assert {a.name for a in artifacts} == {STL_NAME, GLB_NAME}

    go(scenario())


def test_what_was_skipped_before_stays_named() -> None:
    async def scenario() -> None:
        output, _, _ = await kept(bench_run(), {GLB_NAME: PNG}, skipped=("big.glb",))
        assert set(output.skipped) >= {"big.glb", GLB_NAME}

    go(scenario())


def test_a_file_the_store_limit_refuses_is_named_and_not_kept() -> None:
    async def scenario() -> None:
        services.register(ObjectStore, Site())
        small = replace(CONFIG, max_bytes=len(GOOD[GLB_NAME]) + 5)
        output, artifacts = await keep(bench_run(), 1, ran(artifacts={GLB_NAME: GOOD[GLB_NAME], STL_NAME: stl(5)}), small)
        assert [a.name for a in artifacts] == [GLB_NAME] and STL_NAME in output.skipped

    go(scenario())


def test_a_store_that_is_down_costs_the_artifacts_and_not_the_run() -> None:
    async def scenario() -> None:
        site = Site()
        site.down = True
        output, artifacts, _ = await kept(bench_run(), GOOD, site)
        assert artifacts == () and set(GOOD) <= set(output.skipped)

    go(scenario())


def test_after_the_first_store_failure_no_other_file_is_tried() -> None:
    async def scenario() -> None:
        site = Site()
        site.puts_allowed = 1
        output, artifacts, _ = await kept(bench_run(), GOOD, site)
        assert [a.name for a in artifacts] == [MF_NAME]
        assert len(site.calls.of("put")) == 2
        assert {GLB_NAME, STL_NAME} <= set(output.skipped) and len(site.held) == 1

    go(scenario())


def test_two_names_with_the_same_bytes_are_two_records_of_one_object() -> None:
    async def scenario() -> None:
        data = GOOD[GLB_NAME]
        _, artifacts, store = await kept(bench_run(), {"a.glb": data, "b.glb": data})
        assert sorted(a.name for a in artifacts) == ["a.glb", "b.glb"] and {a.sha256 for a in artifacts} == {sha(data)}
        assert list(store.held) == [key_of(HOME, sha(data))]

    go(scenario())


def test_the_same_bytes_of_two_households_are_two_objects() -> None:
    async def scenario() -> None:
        site = Site()
        await kept(bench_run(11), {GLB_NAME: GOOD[GLB_NAME]}, site)
        await kept(bench_run(12), {GLB_NAME: GOOD[GLB_NAME]}, site)
        assert set(site.held) == {key_of(11, sha(GOOD[GLB_NAME])), key_of(12, sha(GOOD[GLB_NAME]))}

    go(scenario())


def test_a_bench_run_with_artifacts_logs_its_counts_and_never_a_name_or_a_byte(caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        with caplog.at_level(logging.INFO):
            await kept(bench_run(), {**GOOD, "wrong.glb": PNG})

    go(scenario())
    [event] = fields_of(caplog, "runs.artifacts")
    values = list(event.values())
    assert 41 in values and 3 in values and 1 in values
    text = log_text(caplog)
    assert "out/model" not in text and "wrong.glb" not in text and sha(GOOD[GLB_NAME]) not in text


def test_a_chat_run_and_a_bench_run_with_nothing_log_nothing(caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        with caplog.at_level(logging.INFO):
            await kept(chat_run(), GOOD)
            await kept(bench_run(), {})

    go(scenario())
    assert fields_of(caplog, "runs.artifacts") == []

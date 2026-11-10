"""The media pod's program against real ffmpeg and a fake speech service: it fetches the file and checks its bytes,
turns chosen moments into one picture whatever the file's length, reads embedded captions, and sends the sound to the
speech service window by window, leaving silence out. A failure is a short reason, never a traceback."""

import asyncio
import base64
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from ashley.runs import media_runner as runner
from ashley.runs.captions import parse_captions
from media_support import recordings, whisper

LIMITS: dict[str, Any] = {"cell_width": 160, "single_width": 320, "qualities": [6, 12], "max_bytes": 200000,
                          "silence_peak": 300, "speech_timeout_s": 10, "fetch_timeout_s": 5}


@pytest.fixture(scope="module")
def files(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    return recordings(tmp_path_factory.mktemp("media"))


@pytest.fixture
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(runner, "WORK", tmp_path)
    return tmp_path


def picture_size(jpeg_b64: str, where: Path) -> tuple[int, int]:
    path = where / "picture.jpg"
    path.write_bytes(base64.b64decode(jpeg_b64))
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    width, height = out.split(",")
    return int(width), int(height)


def test_a_file_is_probed_for_its_length_picture_sound_and_subtitles(files: dict[str, Path]) -> None:
    found = runner.probe(files["talk"])
    assert (found["width"], found["height"], found["audio"], found["subtitles"]) == (320, 240, True, True)
    assert 5.9 < found["duration"] < 6.1
    assert (runner.probe(files["mute"])["audio"], runner.probe(files["plain"])["subtitles"]) == (False, False)
    assert runner.probe(files["song"])["width"] == 0


def test_a_file_ffprobe_cannot_read_is_unreadable(tmp_path: Path) -> None:
    junk = tmp_path / "junk"
    junk.write_bytes(b"not a recording")
    with pytest.raises(runner.Failure, match="unreadable"):
        runner.probe(junk)


def test_one_moment_is_one_frame_at_the_single_width_in_the_videos_proportions(files: dict[str, Path], work: Path) -> None:
    done = runner.frames(files["plain"], {"at": [2.0]}, LIMITS)
    assert (done["kind"], done["count"]) == ("frames", 1)
    assert picture_size(done["jpeg"], work) == (320, 240)


def test_several_moments_are_one_sheet_of_cells_left_to_right_and_down(files: dict[str, Path], work: Path) -> None:
    done = runner.frames(files["plain"], {"at": [0.5, 1.5, 2.5, 3.5]}, LIMITS)
    assert done["count"] == 4 and picture_size(done["jpeg"], work) == (3 * 160, 2 * 120)


def test_the_frames_are_the_moments_asked_not_the_same_one(files: dict[str, Path], work: Path) -> None:
    first = runner.frames(files["plain"], {"at": [0.0]}, LIMITS)["jpeg"]
    later = runner.frames(files["plain"], {"at": [5.0]}, LIMITS)["jpeg"]
    assert first != later


def test_a_moment_outside_the_file_is_clamped_into_it(files: dict[str, Path], work: Path) -> None:
    done = runner.frames(files["plain"], {"at": [-3.0, 9999.0]}, LIMITS)
    assert done["count"] == 2 and picture_size(done["jpeg"], work) == (2 * 160, 120)


def test_the_quality_steps_down_until_the_picture_fits_and_a_picture_that_never_does_is_refused(
        files: dict[str, Path], work: Path) -> None:
    roomy = runner.frames(files["plain"], {"at": [1.0]}, LIMITS)
    size = len(base64.b64decode(roomy["jpeg"]))
    assert runner.frames(files["plain"], {"at": [1.0]}, {**LIMITS, "qualities": [31, 2], "max_bytes": size + 1})["count"] == 1
    with pytest.raises(runner.Failure, match="too_large"):
        runner.frames(files["plain"], {"at": [1.0]}, {**LIMITS, "max_bytes": 100})


def test_a_sound_without_a_picture_has_no_frames(files: dict[str, Path], work: Path) -> None:
    with pytest.raises(runner.Failure, match="no_video"):
        runner.frames(files["song"], {"at": [1.0]}, LIMITS)


def test_embedded_captions_are_returned_as_subrip_with_their_times(files: dict[str, Path], work: Path) -> None:
    done = asyncio.run(runner.transcribe(files["talk"], {"max_audio_s": 900, "whisper": ""}, LIMITS))
    assert done["kind"] == "captions"
    assert [(s.start, s.text) for s in parse_captions(done["srt"])] == [(1.0, "Hello world"), (3.5, "Second cue")]


def task(uri: str, **more: Any) -> dict[str, Any]:
    return {"window_s": 2, "max_audio_s": 900, "whisper": uri, "model": "whisper", "language": None, **more}


def test_sound_with_no_captions_goes_to_the_speech_service_in_windows_stamped_by_their_start(
        files: dict[str, Path], work: Path) -> None:
    async def go() -> tuple[dict[str, Any], int]:
        async with whisper() as service:
            return await runner.transcribe(files["plain"], task(service.uri), LIMITS), service.windows

    done, windows = asyncio.run(go())
    assert done["kind"] == "speech" and windows == 3
    assert done["segments"] == [[0, "window 1"], [2, "window 2"], [4, "window 3"]]


def test_audio_alone_is_transcribed_too(files: dict[str, Path], work: Path) -> None:
    async def go() -> list[list[Any]]:
        async with whisper() as service:
            return (await runner.transcribe(files["song"], task(service.uri), LIMITS))["segments"]

    assert len(asyncio.run(go())) == 3


def test_silence_is_not_sent_to_the_speech_service(files: dict[str, Path], work: Path) -> None:
    async def go() -> tuple[dict[str, Any], int]:
        async with whisper() as service:
            return await runner.transcribe(files["silent"], task(service.uri), LIMITS), service.windows

    done, windows = asyncio.run(go())
    assert done["segments"] == [] and windows == 0


@pytest.mark.parametrize("name,more,reason", [("mute", {}, "no_audio"), ("plain", {"max_audio_s": 3}, "too_long"),
                                              ("plain", {"whisper": ""}, "no_speech_service"),
                                              ("plain", {"whisper": "tcp://127.0.0.1:1"}, "speech_down")])
def test_a_transcript_that_cannot_be_made_says_why(files: dict[str, Path], work: Path, name: str,
                                                   more: dict[str, Any], reason: str) -> None:
    with pytest.raises(runner.Failure, match=reason):
        asyncio.run(runner.transcribe(files[name], task("tcp://127.0.0.1:1", **more), LIMITS))


def test_the_bytes_fetched_must_be_the_ones_named(files: dict[str, Path], tmp_path: Path) -> None:
    data = files["plain"].read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    url = files["plain"].as_uri()
    runner.fetch(url, tmp_path / "ok", len(data), sha, 5)
    assert (tmp_path / "ok").read_bytes() == data
    for size, digest, name in ((len(data) - 1, sha, "short"), (len(data) + 1, sha, "long"), (len(data), "0" * 64, "hash")):
        with pytest.raises(runner.Failure, match="wrong_file"):
            runner.fetch(url, tmp_path / name, size, digest, 5)
    with pytest.raises(runner.Failure, match="fetch_failed"):
        runner.fetch((tmp_path / "missing").as_uri(), tmp_path / "x", 1, sha, 5)


def run_main(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], url: str, task_json: dict[str, Any]) -> str:
    monkeypatch.setenv("ASHLEY_MEDIA_URL", url)
    monkeypatch.setenv("ASHLEY_MEDIA_TASK", json.dumps(task_json))
    monkeypatch.setenv("ASHLEY_MEDIA_LIMITS", json.dumps(LIMITS))
    runner.main()
    return capsys.readouterr().out.strip()


def test_main_prints_one_marked_line_for_an_answer_and_one_failed_line_for_a_failure(
        files: dict[str, Path], work: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    data = files["plain"].read_bytes()
    base = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    line = run_main(monkeypatch, capsys, files["plain"].as_uri(), {"task": "frames", "at": [1.0], **base})
    assert line.startswith(runner.MARK) and json.loads(line[len(runner.MARK):])["count"] == 1
    wrong = run_main(monkeypatch, capsys, files["plain"].as_uri(), {"task": "frames", "at": [1.0], **{**base, "size": 1}})
    assert wrong == runner.FAILED + "wrong_file"

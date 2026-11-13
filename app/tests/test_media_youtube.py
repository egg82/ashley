"""The YouTube captions job, in three places: the media pod's program (`media_runner.youtube_captions`) turning the json3
track yt-dlp wrote (invented, in yt-dlp's shape) into cues and handing yt-dlp nothing but the canonical address of an id;
the pod it runs in (the fetch label that opens public HTTPS to it alone, no file link); and the worker that reads its
answer and logs ids and counts, never words."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import pytest
from ashley.runs import media_config
from ashley.runs import media_runner as runner
from ashley.runs.captions import Segment
from ashley.runs.media import MediaUnavailable, NullMedia, Transcribed
from ashley.runs.media_kubernetes import MARK, KubernetesMedia
from ashley.runs.media_pod import FETCH_LABEL, LABEL, manifest
from ashley.runs.pod_log import PodLog
from media_youtube_support import install, track_text, with_path
from sandbox_support import Clock, FakeKube, Script
from youtube_read_support import VIDEO

CONFIG = media_config.load()
LIMITS: dict[str, Any] = {"captions_timeout_s": 5}
IMAGE = "registry.example/media@sha256:" + "c" * 64


@pytest.fixture
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    install(bin_dir)
    scratch = tmp_path / "work"
    scratch.mkdir()
    track = tmp_path / "track.json3"
    track.write_text(track_text(), encoding="utf-8")
    monkeypatch.setattr(runner, "WORK", scratch)
    monkeypatch.setenv("PATH", with_path(bin_dir))
    monkeypatch.setenv("ARGV_FILE", str(tmp_path / "argv.json"))
    monkeypatch.setenv("TRACK", str(track))
    return tmp_path


def argv_of(work: Path) -> list[str]:
    return json.loads((work / "argv.json").read_text())


def test_the_captured_track_becomes_cues_with_their_start_times_and_the_videos_length() -> None:
    cues, end = runner.json3_segments(track_text())
    assert cues[0] == [1.309, "[music]"] and cues[1] == [1.8, ">> On October 10th, 2026, nearly 7 years"]
    assert [c[0] for c in cues] == sorted(c[0] for c in cues) and len(cues) == 20
    assert all(c[1] == " ".join(c[1].split()) and c[1] for c in cues)
    assert end == pytest.approx(573.337)


@pytest.mark.parametrize("text", ["", "{}", "[]", '{"events": [{"segs": [{"x": 1}], "tStartMs": 1}]}', '{"events": 3}'])
def test_text_that_is_not_a_json3_track_is_refused(text: str) -> None:
    with pytest.raises(runner.Failure, match="bad_captions"):
        runner.json3_segments(text)


def test_a_track_with_no_words_gives_no_cues() -> None:
    assert runner.json3_segments('{"events": [{"tStartMs": 0, "dDurationMs": 9}]}') == ([], 0.009)


def test_the_job_brings_back_the_cues_and_hands_yt_dlp_only_the_canonical_address_of_the_id(work: Path) -> None:
    done = runner.youtube_captions({"video_id": VIDEO}, LIMITS)
    assert done["kind"] == "youtube" and len(done["segments"]) == 20 and done["duration"] == pytest.approx(573.337)
    argv = argv_of(work)
    assert argv[-1] == f"https://www.youtube.com/watch?v={VIDEO}" and "--skip-download" in argv
    assert argv[argv.index("--sub-langs") + 1] == "en" and argv[argv.index("--sub-format") + 1] == "json3"
    assert "--write-subs" in argv and "--write-auto-subs" in argv


@pytest.mark.parametrize("video_id", ["short", "x7Kq2LmN9Rp&x=1", "../../etc/passwd", "x7Kq2LmN9R ", "", "x7Kq2LmN9Rp\n", "--exec=sh"])
def test_anything_but_an_id_never_reaches_yt_dlp(work: Path, video_id: str) -> None:
    with pytest.raises(runner.Failure, match="bad_video"):
        runner.youtube_captions({"video_id": video_id}, LIMITS)
    assert not (work / "argv.json").exists()


@pytest.mark.parametrize("mode,reason", [("none", "no_captions"), ("fail", "fetch_failed")])
def test_a_video_with_no_track_and_a_yt_dlp_that_fails_are_told_apart(
        work: Path, monkeypatch: pytest.MonkeyPatch, mode: str, reason: str) -> None:
    monkeypatch.setenv("MODE", mode)
    with pytest.raises(runner.Failure, match=reason):
        runner.youtube_captions({"video_id": VIDEO}, LIMITS)


def test_a_yt_dlp_that_hangs_is_stopped_at_its_timeout(work: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODE", "hang")
    with pytest.raises(runner.Failure, match="timed_out"):
        runner.youtube_captions({"video_id": VIDEO}, {"captions_timeout_s": 1})


def pod(fetch: bool) -> dict[str, Any]:
    return manifest("media-a1", "", {"task": "youtube_captions", "video_id": VIDEO}, 90, CONFIG, IMAGE, "gvisor", "x", fetch=fetch)


def test_only_a_fetch_pod_carries_the_fetch_label_and_every_media_pod_still_carries_the_media_label() -> None:
    assert pod(True)["metadata"]["labels"] == {LABEL: "true", FETCH_LABEL: "true"}
    assert pod(False)["metadata"]["labels"] == {LABEL: "true"}


def test_the_limits_a_pod_is_given_hold_the_captions_timeout() -> None:
    env = {e["name"]: e["value"] for e in pod(True)["spec"]["containers"][0]["env"]}
    assert json.loads(env["ASHLEY_MEDIA_LIMITS"])["captions_timeout_s"] == CONFIG.captions_timeout_s
    assert CONFIG.captions_timeout_s < CONFIG.captions_deadline_s


LINE = MARK + json.dumps({"kind": "youtube", "duration": 573.3, "segments": [[1.3, "secret words"], [4.0, "more"]]})


async def _whisper() -> str:
    return "tcp://whisper.test:10300"


def worker(fake: FakeKube) -> KubernetesMedia:
    clock = Clock()
    pods = PodLog(fake.api(), "ashley-sandbox", LABEL, CONFIG.log_bytes, CONFIG.poll_s, logging.getLogger("ashley.runs"),
                  "media", sleep=clock.sleep, clock=clock)
    return KubernetesMedia(pods, "gvisor", IMAGE, "http://ashley.test:8080", lambda: b"k" * 32, _whisper, CONFIG)


def captions(fake: FakeKube) -> Transcribed:
    return asyncio.run(worker(fake).youtube_captions("media-a1", VIDEO))


def text_of(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(f"{r.getMessage()} {getattr(r, 'fields', {})}" for r in caplog.records)


def test_the_worker_runs_a_fetch_pod_with_the_id_and_no_file_link_and_returns_the_cues(
        tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeKube(tmp_path / "token", Script(log=LINE))
    with caplog.at_level(logging.INFO, logger="ashley.runs"):
        said = captions(fake)
    assert said == Transcribed("youtube", 573.3, (Segment(1.3, "secret words"), Segment(4.0, "more")))
    created = fake.created[0]
    assert created["metadata"]["labels"][FETCH_LABEL] == "true" and created["spec"]["activeDeadlineSeconds"] == CONFIG.captions_deadline_s
    env = {e["name"]: e["value"] for e in created["spec"]["containers"][0]["env"]}
    assert json.loads(env["ASHLEY_MEDIA_TASK"]) == {"task": "youtube_captions", "video_id": VIDEO} and env["ASHLEY_MEDIA_URL"] == ""
    assert fake.deleted == ["media-a1"]
    logged = text_of(caplog)
    assert "media.youtube_captions" in logged and VIDEO in logged and "'segments': 2" in logged
    assert "secret words" not in logged


def test_a_video_with_no_english_track_is_unavailable_for_that_reason_and_logged_without_words(
        tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeKube(tmp_path / "token", Script(log=runner.FAILED + "no_captions\n"))
    with caplog.at_level(logging.INFO, logger="ashley.runs"), pytest.raises(MediaUnavailable, match="no_captions"):
        captions(fake)
    logged = text_of(caplog)
    assert "media.youtube_captions_failed" in logged and "no_captions" in logged
    assert fake.deleted == ["media-a1"]


@pytest.mark.parametrize("answer", [
    {"kind": "captions", "duration": 1, "srt": ""}, {"kind": "youtube", "duration": 1, "segments": [[0]]},
    {"kind": "youtube", "segments": []}], ids=["wrong kind", "bad segment", "no duration"])
def test_an_answer_that_is_not_youtube_cues_is_refused(tmp_path: Path, answer: dict[str, Any]) -> None:
    fake = FakeKube(tmp_path / "token", Script(log=MARK + json.dumps(answer)))
    with pytest.raises(MediaUnavailable, match="bad_answer"):
        captions(fake)


def test_the_null_object_fetches_nothing() -> None:
    with pytest.raises(MediaUnavailable, match="not_wired"):
        asyncio.run(NullMedia().youtube_captions("media-a1", VIDEO))

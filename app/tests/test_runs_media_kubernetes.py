"""The Kubernetes media worker against a fake API (`sandbox_support.FakeKube`): the pod it asks for has gVisor, no token,
a deadline per task, limits and a pinned image, with the file's link in its environment alone; the answer is read from
the pod's log and checked; the pod is deleted however the job ends; and the log names no link, picture or word."""

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

import pytest
from ashley.files import links
from ashley.runs import media_config
from ashley.runs.captions import Segment
from ashley.runs.media import MediaUnavailable, Sheet, Source, Transcribed
from ashley.runs.media_kubernetes import FAILED, MARK, RUNNER, KubernetesMedia, answer
from ashley.runs.media_pod import LABEL
from ashley.runs.pod_log import PodLog
import logging
from sandbox_support import Clock, FakeKube, Script

CONFIG = media_config.load()
IMAGE = "registry.example/media@sha256:" + "c" * 64
KEY = b"k" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"p" * 30
SOURCE = Source(household_id=3, sha256="a" * 64, size=1234, media_type="video/mp4")
SHEET_LINE = MARK + json.dumps({"kind": "frames", "duration": 61.5, "count": 2, "jpeg": base64.b64encode(JPEG).decode()})
SPEECH_LINE = MARK + json.dumps({"kind": "speech", "duration": 40, "segments": [[0, "hello there"], [20, "second part"]]})
CAPTIONS_LINE = MARK + json.dumps({"kind": "captions", "duration": 9, "srt": "1\n00:00:01,000 --> 00:00:02,000\nhi\n"})


def worker(fake: FakeKube, clock: Clock | None = None) -> KubernetesMedia:
    clock = clock or Clock()
    pods = PodLog(fake.api(), "ashley-sandbox", LABEL, CONFIG.log_bytes, CONFIG.poll_s, logging.getLogger("ashley.runs"),
                  "media", sleep=clock.sleep, clock=clock)
    return KubernetesMedia(pods, "gvisor", IMAGE, "http://ashley.test:8080", KEY, "tcp://whisper.test:10300", CONFIG,
                           wall=lambda: 1000.0)


def frames(fake: FakeKube, at: tuple[float, ...] = (1.0, 2.0)) -> Sheet:
    return asyncio.run(worker(fake).frames("media-a1", SOURCE, at))


def transcribe(fake: FakeKube) -> Transcribed:
    return asyncio.run(worker(fake).transcribe("media-a1", SOURCE, "en"))


@pytest.fixture
def fake(tmp_path: Path) -> FakeKube:
    return FakeKube(tmp_path / "token", Script(log=SHEET_LINE))


def container(fake: FakeKube) -> dict[str, Any]:
    assert len(fake.created) == 1
    return fake.created[0]["spec"]["containers"][0]


def env_of(fake: FakeKube) -> dict[str, str]:
    return {e["name"]: e["value"] for e in container(fake)["env"]}


def test_frames_are_the_sheet_the_pod_printed_and_the_pod_is_deleted(fake: FakeKube) -> None:
    assert frames(fake) == Sheet(JPEG, 2, 61.5)
    assert fake.deleted == ["media-a1"] and not fake.pods


def test_the_pod_is_locked_down_runs_the_pinned_image_and_has_the_deadline_of_its_task(fake: FakeKube) -> None:
    frames(fake)
    spec = fake.created[0]["spec"]
    assert spec["runtimeClassName"] == "gvisor" and spec["automountServiceAccountToken"] is False
    assert spec["restartPolicy"] == "Never" and spec["hostNetwork"] is False and spec["enableServiceLinks"] is False
    assert spec["activeDeadlineSeconds"] == CONFIG.frames_deadline_s
    box = container(fake)
    assert box["image"] == IMAGE and box["command"][-1] == RUNNER
    storage = f"{CONFIG.ephemeral_mib}Mi"
    assert box["resources"]["limits"] == {"cpu": CONFIG.cpu, "memory": CONFIG.memory, "ephemeral-storage": storage}
    assert spec["volumes"][0]["emptyDir"]["sizeLimit"] == f"{CONFIG.work_mib}Mi"
    context = box["securityContext"]
    assert context["runAsNonRoot"] is True and context["readOnlyRootFilesystem"] is True
    assert context["allowPrivilegeEscalation"] is False and context["capabilities"] == {"drop": ["ALL"]}
    assert fake.created[0]["metadata"]["labels"] == {LABEL: "true"}


def test_the_file_link_is_a_short_lived_grant_of_that_file_in_the_environment_alone(fake: FakeKube) -> None:
    frames(fake)
    url = env_of(fake)["ASHLEY_MEDIA_URL"]
    assert url.startswith("http://ashley.test:8080" + links.PATH)
    grant = links.check(KEY, url.rsplit("/", 1)[1], now=1000.0)
    assert grant == links.Grant(3, "a" * 64, "video/mp4", False, 1000 + CONFIG.link_ttl_s)
    assert links.check(KEY, url.rsplit("/", 1)[1], now=1000.0 + CONFIG.link_ttl_s) is None
    assert url not in json.dumps(container(fake)["command"])


def test_the_task_names_the_moments_and_the_files_size_and_hash(fake: FakeKube) -> None:
    frames(fake, (4.5, 9.0))
    assert json.loads(env_of(fake)["ASHLEY_MEDIA_TASK"]) == {"task": "frames", "at": [4.5, 9.0], "size": 1234,
                                                             "sha256": "a" * 64}
    assert json.loads(env_of(fake)["ASHLEY_MEDIA_LIMITS"])["max_bytes"] == CONFIG.max_sheet_bytes


@pytest.mark.parametrize("at", [(), tuple(float(n) for n in range(CONFIG.max_frames + 1))], ids=["none", "too many"])
def test_no_frames_or_more_than_the_limit_is_refused_before_any_pod(fake: FakeKube, at: tuple[float, ...]) -> None:
    with pytest.raises(MediaUnavailable, match="bad_frames"):
        frames(fake, at)
    assert fake.created == []


def test_a_transcript_from_speech_is_the_segments_in_order_with_the_speech_service_and_a_longer_deadline(fake: FakeKube) -> None:
    fake.script = Script(log=SPEECH_LINE)
    assert transcribe(fake) == Transcribed("speech", 40.0, (Segment(0.0, "hello there"), Segment(20.0, "second part")))
    task = json.loads(env_of(fake)["ASHLEY_MEDIA_TASK"])
    assert (task["whisper"], task["model"], task["language"], task["window_s"]) == (
        "tcp://whisper.test:10300", CONFIG.whisper_model, "en", CONFIG.window_s)
    assert fake.created[0]["spec"]["activeDeadlineSeconds"] == CONFIG.transcribe_deadline_s


def test_embedded_captions_come_back_parsed(fake: FakeKube) -> None:
    fake.script = Script(log=CAPTIONS_LINE)
    assert transcribe(fake) == Transcribed("captions", 9.0, (Segment(1.0, "hi"),))


@pytest.mark.parametrize("text,reason", [
    (FAILED + "no_video\n", "no_video"), ("", "no_answer"), ("chatter\n", "no_answer"), (MARK + "{not json\n", "bad_answer"),
    (MARK + "[1]\n", "bad_answer"),
    (MARK + json.dumps({"kind": "frames", "duration": 1, "count": 1, "jpeg": base64.b64encode(b"GIF89a").decode()}) + "\n",
     "bad_answer"),
    (MARK + json.dumps({"kind": "frames", "duration": 1, "count": 1, "jpeg": "!!"}) + "\n", "bad_answer"),
    (MARK + json.dumps({"kind": "speech", "duration": 1, "segments": [[0]]}) + "\n", "bad_answer")],
    ids=["failed line", "empty", "chatter", "not json", "not an object", "not a jpeg", "not base64", "bad segment"])
def test_what_the_pod_printed_that_is_not_an_answer_is_refused_with_its_reason(fake: FakeKube, text: str, reason: str) -> None:
    fake.script = Script(log=text)
    with pytest.raises(MediaUnavailable, match=reason):
        if reason == "bad_answer" and "speech" in text:
            transcribe(fake)
        else:
            frames(fake)
    assert fake.deleted == ["media-a1"]


def test_the_last_answer_line_wins() -> None:
    first = MARK + json.dumps({"kind": "frames", "n": 1})
    assert answer(first + "\n" + MARK + json.dumps({"kind": "frames", "n": 2}) + "\n")["n"] == 2


def test_a_pod_that_never_leaves_pending_or_runs_out_of_time_is_deleted_and_unavailable(fake: FakeKube) -> None:
    fake.script = Script(phases=["Pending"], log=SHEET_LINE)
    with pytest.raises(MediaUnavailable, match="never_ran"):
        frames(fake)
    fake.script = Script(phases=["Running"], log=SHEET_LINE)
    with pytest.raises(MediaUnavailable, match="timed_out"):
        frames(fake)
    assert fake.deleted == ["media-a1", "media-a1"]


def test_a_refused_pod_is_unavailable(fake: FakeKube) -> None:
    fake.fail = lambda request: 403 if request.method == "POST" else None
    with pytest.raises(MediaUnavailable, match="http 403"):
        frames(fake)


def test_a_media_pod_a_stopped_app_left_behind_is_swept_but_not_a_fresh_one(fake: FakeKube) -> None:
    for name, created in (("media-old", "2000-01-01T00:00:00Z"), ("media-new", "2099-01-01T00:00:00Z")):
        fake.pods[name] = {"metadata": {"name": name, "creationTimestamp": created, "labels": {LABEL: "true"}}}
    frames(fake)
    assert "media-old" in fake.deleted and "media-new" not in fake.deleted


def test_the_log_counts_what_was_done_and_never_the_link_the_picture_or_the_words(fake: FakeKube,
                                                                                  caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="ashley.runs")
    frames(fake)
    fake.script = Script(log=SPEECH_LINE)
    transcribe(fake)
    text = "\n".join(f"{r.getMessage()} {getattr(r, 'fields', {})}" for r in caplog.records)
    assert "media.frames" in text and "media.transcribed" in text and "'frames': 2" in text and "'segments': 2" in text
    assert "/api/files/" not in text and "hello there" not in text and SHEET_LINE[len(MARK):] not in text

"""The program a media pod runs (`python -I -B -c <this file's text>`) in the pinned media image (Python, ffmpeg and
`wyoming`): fetch one file of the object store from the app by the link in `ASHLEY_MEDIA_URL`, check it is the bytes
named (`size`, `sha256`), then do the task in `ASHLEY_MEDIA_TASK` (JSON) and print one line, `MARK` then JSON, or
`FAILED` then a short reason.

- `frames`: a JPEG of the moments `at` (seconds), one frame full size or several as a sheet of cells, left to right
  then down, in the order given.
- `transcribe`: the file's embedded captions as SubRip text when it has some; else its sound cut into windows of
  `window_s` seconds, each sent to the speech service at `whisper` (a Wyoming `tcp://host:port`), as the segments
  `[start, text]`. A window of near silence is not sent.

- `youtube_captions`: no file is fetched; yt-dlp is given the watch address built here from `video_id` (an 11-character
  id, nothing else reaches it) and brings back the English captions (the manual track, else the automatic one) as
  json3, which become the segments `[start, text]`.

Never prints the link, which is a credential, nor what was said beyond the segments the task asks for."""

import asyncio
import base64
import hashlib
import json
import os
import re
import subprocess
import urllib.request
from array import array
from collections.abc import Iterator
from pathlib import Path
from typing import Any

MARK = "ashley-media "
FAILED = "ashley-media-failed "
WORK = Path("/work")
CHUNK = 1 << 16
PCM_RATE = 16000
PCM_WIDTH = 2
FFMPEG = ["ffmpeg", "-v", "error", "-nostdin", "-y"]
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
WATCH = "https://www.youtube.com/watch?v="


class Failure(Exception):
    """The task cannot be done, for `reason` (a short word)."""


def fetch(url: str, dest: Path, size: int, sha256: str, timeout_s: int) -> None:
    """Download `url` into `dest`; the bytes must be `size` long and hash to `sha256`."""
    digest = hashlib.sha256()
    got = 0
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response, dest.open("wb") as out:
            while chunk := response.read(CHUNK):
                got += len(chunk)
                if got > size:
                    raise Failure("wrong_file")
                digest.update(chunk)
                out.write(chunk)
    except OSError as e:
        raise Failure("fetch_failed") from e
    if got != size or digest.hexdigest() != sha256:
        raise Failure("wrong_file")


def run(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(args, capture_output=True, check=False)


def probe(path: Path) -> dict[str, Any]:
    """`duration` (seconds), `width`, `height` of the first video stream (0 for none), and whether it has `audio` and
    `subtitles` streams. Raises Failure `unreadable` for a file ffprobe cannot read."""
    done = run("ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
               "-of", "json", str(path))
    try:
        data: dict[str, Any] = json.loads(done.stdout.decode("utf-8", errors="replace"))
        streams: list[dict[str, Any]] = data["streams"]
        duration = float(data["format"]["duration"])
    except (ValueError, KeyError, TypeError) as e:
        raise Failure("unreadable") from e
    videos = [s for s in streams if s.get("codec_type") == "video"]
    video: dict[str, Any] = videos[0] if videos else {}
    kinds: set[Any] = {s.get("codec_type") for s in streams}
    return {"duration": duration, "width": int(video.get("width", 0)), "height": int(video.get("height", 0)),
            "audio": "audio" in kinds, "subtitles": "subtitle" in kinds}


def cell_size(width: int, height: int, cell_w: int) -> tuple[int, int]:
    """A cell `cell_w` wide with the video's own proportions, height even and between half and double the width."""
    if width <= 0 or height <= 0:
        return cell_w, cell_w * 9 // 16 // 2 * 2
    return cell_w, min(cell_w * 2, max(cell_w // 2, round(cell_w * height / width))) // 2 * 2


def grab(path: Path, at: list[float], duration: float, size: tuple[int, int], quality: int, out: Path) -> Path:
    """The frame at each of `at` (clamped into the file) as `out/<n>.jpg`, `size` each, then the sheet of them
    (`out/sheet.jpg`) when there are several; the picture's path. Raises Failure `no_frame`."""
    cell_w, cell_h = size
    fit = f"scale={cell_w}:{cell_h}:force_original_aspect_ratio=decrease,pad={cell_w}:{cell_h}:(ow-iw)/2:(oh-ih)/2"
    last = max(0.0, duration - 0.2)
    for n, moment in enumerate(at, 1):
        done = run(*FFMPEG, "-ss", f"{min(max(moment, 0.0), last):.3f}", "-i", str(path), "-frames:v", "1", "-vf", fit,
                   "-q:v", str(quality), str(out / f"{n}.jpg"))
        if done.returncode != 0 or not (out / f"{n}.jpg").exists():
            raise Failure("no_frame")
    if len(at) == 1:
        return out / "1.jpg"
    columns = min(len(at), 3)
    rows = -(-len(at) // columns)
    done = run(*FFMPEG, "-i", str(out / "%d.jpg"), "-vf", f"tile={columns}x{rows}", "-frames:v", "1",
               "-q:v", str(quality), str(out / "sheet.jpg"))
    if done.returncode != 0 or not (out / "sheet.jpg").exists():
        raise Failure("no_frame")
    return out / "sheet.jpg"


def frames(path: Path, task: dict[str, Any], limits: dict[str, Any]) -> dict[str, Any]:
    """The `frames` task: the picture as base64 JPEG, under `max_bytes` (the quality steps down until it fits)."""
    info = probe(path)
    if info["width"] <= 0:
        raise Failure("no_video")
    at = [float(t) for t in task["at"]]
    wide = limits["single_width"] if len(at) == 1 else limits["cell_width"]
    size = cell_size(info["width"], info["height"], wide)
    out = WORK / "frames"
    out.mkdir(exist_ok=True)
    for quality in limits["qualities"]:
        picture = grab(path, at, info["duration"], size, quality, out).read_bytes()
        if len(picture) <= limits["max_bytes"]:
            return {"kind": "frames", "duration": info["duration"], "count": len(at),
                    "jpeg": base64.b64encode(picture).decode("ascii")}
    raise Failure("too_large")


def captions(path: Path) -> str | None:
    """The first subtitle stream as SubRip text; None when the file has none that ffmpeg can turn into text."""
    out = WORK / "captions.srt"
    done = run(*FFMPEG, "-i", str(path), "-map", "0:s:0", "-f", "srt", str(out))
    if done.returncode != 0 or not out.exists():
        return None
    return out.read_text(encoding="utf-8", errors="replace").strip() or None


def windows(path: Path, window_s: int, max_audio_s: int) -> Iterator[tuple[int, bytes]]:
    """The file's sound as mono 16 kHz 16-bit PCM cut into windows of `window_s` seconds, each with its start."""
    wanted = window_s * PCM_RATE * PCM_WIDTH
    proc = subprocess.Popen([*FFMPEG, "-i", str(path), "-vn", "-ac", "1", "-ar", str(PCM_RATE), "-t", str(max_audio_s),
                             "-f", "s16le", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdout is not None
    start = 0
    try:
        while data := proc.stdout.read(wanted):
            yield start, data
            start += window_s
    finally:
        proc.stdout.close()
        proc.wait()


def quiet(pcm: bytes, peak: int) -> bool:
    """Whether no sample of `pcm` reaches `peak`."""
    samples = array("h")
    samples.frombytes(pcm[:len(pcm) // PCM_WIDTH * PCM_WIDTH])
    return not samples or max(max(samples), -min(samples)) < peak


async def say(pcm: bytes, uri: str, model: str, language: str | None, timeout_s: float) -> str:
    """The speech service's text for `pcm`."""
    from wyoming.asr import Transcribe, Transcript
    from wyoming.audio import AudioChunk, AudioStart, AudioStop
    from wyoming.client import AsyncClient

    async with AsyncClient.from_uri(uri, connect_timeout=timeout_s, read_timeout=timeout_s) as client:
        async with asyncio.timeout(timeout_s):
            await client.write_event(Transcribe(name=model, language=language).event())
            await client.write_event(AudioStart(PCM_RATE, PCM_WIDTH, 1).event())
            for at in range(0, len(pcm), CHUNK):
                await client.write_event(AudioChunk(PCM_RATE, PCM_WIDTH, 1, pcm[at:at + CHUNK]).event())
            await client.write_event(AudioStop().event())
            while (event := await client.read_event()) is not None:
                if Transcript.is_type(event.type):
                    return Transcript.from_event(event).text
    raise Failure("speech_failed")


async def speak(path: Path, task: dict[str, Any], limits: dict[str, Any]) -> list[list[Any]]:
    """The segments `[start, text]` of the file's sound, in order, windows of silence left out."""
    segments: list[list[Any]] = []
    for start, pcm in windows(path, task["window_s"], task["max_audio_s"]):
        if quiet(pcm, limits["silence_peak"]):
            continue
        try:
            text = await say(pcm, task["whisper"], task["model"], task.get("language"), limits["speech_timeout_s"])
        except (OSError, TimeoutError, EOFError) as e:
            raise Failure("speech_down") from e
        if text.strip():
            segments.append([start, text.strip()])
    return segments


async def transcribe(path: Path, task: dict[str, Any], limits: dict[str, Any]) -> dict[str, Any]:
    """The `transcribe` task: the embedded captions, else what was said."""
    info = probe(path)
    if info["subtitles"]:
        found = captions(path)
        if found is not None:
            return {"kind": "captions", "duration": info["duration"], "srt": found}
    if not info["audio"]:
        raise Failure("no_audio")
    if info["duration"] > task["max_audio_s"]:
        raise Failure("too_long")
    if not task["whisper"]:
        raise Failure("no_speech_service")
    return {"kind": "speech", "duration": info["duration"], "segments": await speak(path, task, limits)}


def json3_segments(text: str) -> tuple[list[list[Any]], float]:
    """The cues of a YouTube json3 caption track as `[start, text]` (seconds, words joined and spaces collapsed; events
    with no words, such as the line breaks of automatic captions, left out) and the seconds the last event ends. Raises
    Failure `bad_captions` for text that is not a json3 track."""
    try:
        events: list[dict[str, Any]] = json.loads(text)["events"]
        cues = [[e["tStartMs"] / 1000, " ".join("".join(s["utf8"] for s in e["segs"]).split())] for e in events if "segs" in e]
        end = max((e["tStartMs"] + e.get("dDurationMs", 0) for e in events), default=0) / 1000
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise Failure("bad_captions") from e
    return [c for c in cues if c[1]], end


def youtube_captions(task: dict[str, Any], limits: dict[str, Any]) -> dict[str, Any]:
    """The `youtube_captions` task. Raises Failure `bad_video`, `timed_out`, `fetch_failed` (yt-dlp failed) or
    `no_captions` (the video has no English track)."""
    video_id = str(task["video_id"])
    if not VIDEO_ID.fullmatch(video_id):
        raise Failure("bad_video")
    argv = ["yt-dlp", "--skip-download", "--no-playlist", "--no-warnings", "--write-subs", "--write-auto-subs",
            "--sub-langs", "en", "--sub-format", "json3", "-o", str(WORK / "video.%(ext)s"), WATCH + video_id]
    try:
        done = subprocess.run(argv, capture_output=True, check=False, timeout=limits["captions_timeout_s"])
    except subprocess.TimeoutExpired as e:
        raise Failure("timed_out") from e
    if done.returncode != 0:
        raise Failure("fetch_failed")
    tracks = sorted(WORK.glob("video.*.json3"))
    if not tracks:
        raise Failure("no_captions")
    cues, duration = json3_segments(tracks[0].read_text(encoding="utf-8", errors="replace"))
    if not cues:
        raise Failure("no_captions")
    return {"kind": "youtube", "duration": duration, "segments": cues}


def on_file(task: dict[str, Any], limits: dict[str, Any]) -> dict[str, Any]:
    """Fetch the file by the link in the environment and do the `frames` or `transcribe` task on it."""
    path = WORK / "input"
    fetch(os.environ["ASHLEY_MEDIA_URL"], path, task["size"], task["sha256"], limits["fetch_timeout_s"])
    return asyncio.run(transcribe(path, task, limits)) if task["task"] == "transcribe" else frames(path, task, limits)


def main() -> None:
    task: dict[str, Any] = json.loads(os.environ["ASHLEY_MEDIA_TASK"])
    limits: dict[str, Any] = json.loads(os.environ["ASHLEY_MEDIA_LIMITS"])
    try:
        done = youtube_captions(task, limits) if task["task"] == "youtube_captions" else on_file(task, limits)
    except Failure as e:
        print(FAILED + str(e), flush=True)
        return
    print(MARK + json.dumps(done, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

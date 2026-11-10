"""The media jobs' tunables, data in `media.json` beside this module. Frames: the `cell_width` of each frame of a sheet
and the `single_width` of a lone frame (pixels), the most frames one look takes (`max_frames`), the JPEG `qualities`
tried in turn (ffmpeg `-q:v`, lower is better) until the picture is under `max_sheet_bytes`. Speech: the sound is cut
into windows of `window_s` seconds, the longest sound taken is `max_audio_s`, a window whose loudest sample is under
`silence_peak` (of 32768) is not sent, `speech_timeout_s` bounds each window's answer and `whisper_model` is the model
the speech service is asked for. The pod: `fetch_timeout_s` to download the file, `link_ttl_s` how long its link lives,
the pod's deadline for each task (`frames_deadline_s`, `transcribe_deadline_s`, `captions_deadline_s`; a captions job
fetches no file, and `captions_timeout_s` bounds its yt-dlp inside that), `cpu`, `cpu_request`, `memory`,
`work_mib` (its scratch, which holds the file) and `ephemeral_mib` (its ephemeral-storage request and limit, scratch and
log), the most of its log read (`log_bytes`, room for a base64 picture of `max_sheet_bytes` and a long transcript) and
how often it is asked whether it finished (`poll_s`)."""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("media.json")
BASE64_NUMERATOR, BASE64_DENOMINATOR = 4, 3
LINE_OVERHEAD = 1024


@dataclass(frozen=True)
class MediaConfig:
    cell_width: int
    single_width: int
    max_frames: int
    qualities: tuple[int, ...]
    max_sheet_bytes: int
    window_s: int
    max_audio_s: int
    silence_peak: int
    speech_timeout_s: int
    whisper_model: str
    fetch_timeout_s: int
    link_ttl_s: int
    frames_deadline_s: int
    transcribe_deadline_s: int
    captions_deadline_s: int
    captions_timeout_s: int
    cpu: str
    cpu_request: str
    memory: str
    work_mib: int
    ephemeral_mib: int
    log_bytes: int
    poll_s: float


def load() -> MediaConfig:
    """The tunables shipped in `media.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> MediaConfig:
    """A MediaConfig from JSON already parsed. Raises ValueError when a key is missing or unknown, a value has the wrong
    type or is not positive, `qualities` is not a non-empty list of 1 to 31, `silence_peak` is over 32767, `work_mib`
    is not under `ephemeral_mib`, a deadline does not leave the file time to be fetched, `captions_timeout_s` is not under its deadline, or `log_bytes` has no room for
    a base64 picture of `max_sheet_bytes`."""
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError("media config is an object")
    raw = dict[object, object](loose)
    names = [f.name for f in fields(MediaConfig)]
    if sorted(str(k) for k in raw) != sorted(names):
        raise ValueError(f"media config keys are {names}")
    values: dict[str, Any] = {}
    for f in fields(MediaConfig):
        value = raw[f.name]
        if f.type is str and (not isinstance(value, str) or not value):
            raise ValueError(f"{f.name}: expected a non-empty string")
        if f.type is int and (type(value) is not int or value <= 0):
            raise ValueError(f"{f.name}: expected a positive integer")
        if f.type is float and (type(value) not in (int, float) or float(str(value)) <= 0):
            raise ValueError(f"{f.name}: expected a positive number")
        values[f.name] = value
    values["qualities"] = _qualities(raw["qualities"])
    config = MediaConfig(**values)
    if config.silence_peak > 32767:
        raise ValueError("silence_peak: at most 32767")
    if config.work_mib >= config.ephemeral_mib:
        raise ValueError("ephemeral_mib: more than work_mib")
    if min(config.frames_deadline_s, config.transcribe_deadline_s) <= config.fetch_timeout_s:
        raise ValueError("frames_deadline_s and transcribe_deadline_s: longer than fetch_timeout_s")
    if config.captions_timeout_s >= config.captions_deadline_s:
        raise ValueError("captions_deadline_s: longer than captions_timeout_s")
    if config.max_sheet_bytes * BASE64_NUMERATOR // BASE64_DENOMINATOR + LINE_OVERHEAD > config.log_bytes:
        raise ValueError("log_bytes: room for a picture of max_sheet_bytes in base64")
    return config


def _qualities(value: object) -> tuple[int, ...]:
    loose: Any = value
    if not isinstance(value, list) or not value:
        raise ValueError("qualities: a non-empty list")
    found = tuple(list[object](loose))
    if not all(type(q) is int and 1 <= q <= 31 for q in found):
        raise ValueError("qualities: whole numbers from 1 to 31")
    return tuple(int(str(q)) for q in found)

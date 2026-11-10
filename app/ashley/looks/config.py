"""The look tunables, data in `looks.json` beside this module: the screenshot's `width` and `height` (CSS pixels) and the tallest it is cut to (`max_height`) and
`jpeg_quality`; the most bytes of a picture she is given (`max_image_bytes`, for an image piece's own bytes and for a
screenshot alike) and the most looks one turn takes (`max_looks_per_turn`); how an image is made fit to be seen
(`ashley.looks.pictures`): its longest side (`max_image_px`), the JPEG quality it is encoded at
(`image_jpeg_quality`), the most pixels a source may hold before it is refused unread (`max_image_pixels`), and the
smallest crop of it she may ask for, as a fraction of each side (`min_region`); how long the page's link lives
(`link_ttl_s`); the browser pod's `pod_deadline_s` (its `activeDeadlineSeconds`), `ready_timeout_s` (how long the page
has to say it is drawn), `cpu`, `cpu_request`, `memory`, `shm_mib` (its `/dev/shm`), `home_mib` (its writable home) and `ephemeral_mib` (its ephemeral-storage request and limit: the home and its log) and the most of its log read
(`log_bytes`, room for a base64 picture of `max_image_bytes` and a page of `read_bytes`), the most of a page a read pod
brings back (`read_bytes`, `shooter.read`); and how often the pod is asked whether it has finished
(`poll_s`); and the warm pod's: how often it is checked (`warm_tick_s`), the longest it lives (`warm_max_age_s`) and how
long a look waits to reach it before taking a pod of its own (`warm_connect_s`)."""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("looks.json")
BASE64_NUMERATOR, BASE64_DENOMINATOR = 4, 3
LINE_OVERHEAD = 256


@dataclass(frozen=True)
class LooksConfig:
    width: int
    height: int
    max_height: int
    jpeg_quality: int
    max_image_bytes: int
    max_image_px: int
    image_jpeg_quality: int
    max_image_pixels: int
    min_region: float
    max_looks_per_turn: int
    link_ttl_s: int
    pod_deadline_s: int
    ready_timeout_s: int
    cpu: str
    cpu_request: str
    memory: str
    shm_mib: int
    home_mib: int
    ephemeral_mib: int
    log_bytes: int
    read_bytes: int
    poll_s: float
    warm_tick_s: float
    warm_max_age_s: int
    warm_connect_s: float


def load() -> LooksConfig:
    """The tunables shipped in `looks.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> LooksConfig:
    """A LooksConfig from JSON already parsed. Raises ValueError when a key is missing or unknown, a value has the
    wrong type or is not positive, `max_height` is under `height`, `jpeg_quality` is over 100, `ephemeral_mib` is not over `home_mib`, the pod's deadline leaves the page no time to be drawn
    in, or `log_bytes` has no room for a picture of `max_image_bytes` in base64."""
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError("looks config is an object")
    raw = dict[object, object](loose)
    names = [f.name for f in fields(LooksConfig)]
    if sorted(str(k) for k in raw) != sorted(names):
        raise ValueError(f"looks config keys are {names}")
    for f in fields(LooksConfig):
        value = raw[f.name]
        if f.type is str and (not isinstance(value, str) or not value):
            raise ValueError(f"{f.name}: expected a non-empty string")
        if f.type is int and (type(value) is not int or value <= 0):
            raise ValueError(f"{f.name}: expected a positive integer")
        if f.type is float and (type(value) not in (int, float) or float(str(value)) <= 0):
            raise ValueError(f"{f.name}: expected a positive number")
    config = LooksConfig(**{name: loose[name] for name in names})
    if config.max_height < config.height:
        raise ValueError("max_height: at least height")
    if config.ephemeral_mib <= config.home_mib:
        raise ValueError("ephemeral_mib: more than home_mib")
    if config.jpeg_quality > 100 or config.image_jpeg_quality > 100:
        raise ValueError("jpeg_quality and image_jpeg_quality: at most 100")
    if config.min_region > 1:
        raise ValueError("min_region: at most 1")
    if config.pod_deadline_s <= config.ready_timeout_s:
        raise ValueError("pod_deadline_s: longer than ready_timeout_s")
    if config.max_image_bytes * BASE64_NUMERATOR // BASE64_DENOMINATOR + LINE_OVERHEAD > config.log_bytes:
        raise ValueError("log_bytes: room for a picture of max_image_bytes in base64")
    if config.read_bytes * BASE64_NUMERATOR // BASE64_DENOMINATOR + LINE_OVERHEAD > config.log_bytes:
        raise ValueError("log_bytes: room for a page of read_bytes in base64")
    return config

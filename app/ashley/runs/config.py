"""The sandbox's tunables, data in `runs.json` beside this module. What every run shares is top level: where a pod goes
(`namespace`, `runtime_class`), the longest script and input taken (`max_script_chars`, `max_stdin_chars`), how much of
each output stream and each file comes back (`output_chars`, `file_chars`, `max_files`, one reply shape for every
language), and how often the pod is asked whether it has finished (`poll_s`).

Each language is one `Profile` under `languages`, and Python's is required: how long the script may run
(`script_timeout_s`) and the pod may live (`pod_deadline_s`, its `activeDeadlineSeconds`, which includes starting it), its
`cpu` limit and `cpu_request`, its `memory` (request and limit), the size of its working directory (`work_mib`), the most of
the pod's log read (`log_bytes`, which varies with the language's output) and `artifact_bytes` (the most binary output it
carries back, left out for none) and `input_bytes` (the most binary input it is given, left out for none). Python's profile also carries its pinned `image`; any other language's is given at start
(`CAD_IMAGE`) through `with_image`, and a language with no image is not run."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, get_args

from .loose import as_object
from .model import Language

FILE = Path(__file__).with_name("runs.json")
PINNED = re.compile(r"[^@\s]+@sha256:[0-9a-f]{64}")
WORST_BYTES_PER_CHAR = 6
"""A control character in the runner's JSON line is `\\u00XX`."""
LINE_OVERHEAD = 1024
OPTIONAL = ["artifact_bytes", "input_bytes"]
MIB = 1024 * 1024


@dataclass(frozen=True)
class Profile:
    """How one language's pod is made. `image` is empty for a language not given one."""

    image: str
    script_timeout_s: int
    pod_deadline_s: int
    cpu: str
    cpu_request: str
    memory: str
    work_mib: int
    log_bytes: int
    artifact_bytes: int = 0
    input_bytes: int = 0


@dataclass(frozen=True)
class RunsConfig:
    namespace: str
    runtime_class: str
    max_script_chars: int
    max_stdin_chars: int
    output_chars: int
    file_chars: int
    max_files: int
    poll_s: float
    languages: Mapping[str, Profile]

    def profile(self, language: Language) -> Profile | None:
        """The pod profile for `language`, or None when it is not run (no profile, or no image given it)."""
        found = self.languages.get(language)
        return found if found is not None and found.image else None

    def offered(self) -> tuple[Language, ...]:
        """The languages it runs, Python first."""
        return tuple(lang for lang in get_args(Language) if self.profile(lang) is not None)

    def longest_deadline_s(self) -> int:
        """The longest `pod_deadline_s` of any profile, run or not."""
        return max(p.pod_deadline_s for p in self.languages.values())

    def with_image(self, language: str, image: str) -> "RunsConfig":
        """This config with `language` run in `image`. Raises ValueError for an image not pinned by digest or a
        language with no profile."""
        if language not in self.languages:
            raise ValueError(f"{language}: no profile to give an image")
        if not PINNED.fullmatch(image):
            raise ValueError("image: pinned by a full digest (name@sha256:<64 lowercase hex>)")
        return replace(self, languages={**self.languages, language: replace(self.languages[language], image=image)})


def load() -> RunsConfig:
    """The tunables shipped in `runs.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> RunsConfig:
    """A RunsConfig from JSON already parsed. Raises ValueError when a key is missing or unknown, a value has the
    wrong type or is not positive, `languages` lacks Python or names another thing, an image is not pinned by digest
    (Python's is in the file; another language's is given at start), a profile's pod deadline leaves the
    script no time to be stopped by its own timeout first, its log has no room for both output streams, or its artifacts
    or inputs may be larger than its working directory."""
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError("runs config is an object")
    raw = dict[object, object](loose)
    names = [f.name for f in fields(RunsConfig) if f.name != "languages"]
    if sorted(str(k) for k in raw if k != "languages") != sorted(names) or "languages" not in raw:
        raise ValueError(f"runs config keys are {names} and languages")
    _check_types(RunsConfig, raw, skip="languages")
    config = RunsConfig(**{name: loose[name] for name in names}, languages=_profiles(raw["languages"]))
    for profile in config.languages.values():
        _check_room(profile, config.output_chars)
    return config


def _profiles(raw: object) -> dict[str, Profile]:
    loose: Any = raw
    if not isinstance(raw, dict):
        raise ValueError("languages: an object of profiles by language")
    required = [f.name for f in fields(Profile) if f.name not in ("image", "artifact_bytes", "input_bytes")]
    found: dict[str, Profile] = {}
    for language, body in dict[str, Any](loose).items():
        if language not in get_args(Language):
            raise ValueError(f"languages: {language!r} is not a language")
        given = as_object(body)
        own = ["image"] if language == "python" else []
        if given is None or not set(required + own) <= set(given) or not set(given) <= set(required + own + OPTIONAL):
            raise ValueError(f"languages.{language}: keys are {required + own}, and optionally {OPTIONAL}")
        _check_types(Profile, {"artifact_bytes": 1, "input_bytes": 1, **given}, f"languages.{language}.", skip="" if own else "image")
        if own and not PINNED.fullmatch(given["image"]):
            raise ValueError("image: pinned by a full digest (name@sha256:<64 lowercase hex>)")
        values: dict[str, Any] = {"artifact_bytes": 0, "input_bytes": 0, "image": "", **given}
        found[language] = Profile(**values)
    if "python" not in found:
        raise ValueError("languages: python has a profile")
    return found


def _check_types(kind: type, raw: Mapping[Any, object], where: str = "", skip: str = "") -> None:
    for f in (f for f in fields(kind) if f.name != skip):
        value = raw[f.name]
        if f.type is str and (not isinstance(value, str) or not value):
            raise ValueError(f"{where}{f.name}: expected a non-empty string")
        if f.type is int and (type(value) is not int or value <= 0):
            raise ValueError(f"{where}{f.name}: expected a positive integer")
        if f.type is float and (type(value) not in (int, float) or float(str(value)) <= 0):
            raise ValueError(f"{where}{f.name}: expected a positive number")


def _check_room(profile: Profile, output_chars: int) -> None:
    if profile.pod_deadline_s <= profile.script_timeout_s:
        raise ValueError("pod_deadline_s: longer than script_timeout_s")
    if 2 * output_chars * WORST_BYTES_PER_CHAR + LINE_OVERHEAD > profile.log_bytes:
        raise ValueError("log_bytes: room for both output streams, each character escaped at its longest")
    if profile.artifact_bytes > profile.work_mib * MIB:
        raise ValueError("artifact_bytes: no more than the working directory holds")
    if profile.input_bytes > profile.work_mib * MIB:
        raise ValueError("input_bytes: no more than the working directory holds")

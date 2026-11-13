"""Stand-ins for the image tests: the captured provider responses, scripted image makers, and a router over them."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, get_args

from ashley.inference.image import Aspect
from ashley.inference.image_provider import ImageMaker, Made
from ashley.inference.image_quota import ImageCap, ImageLimit
from ashley.inference.model import Route, Task, Usage
from catalogue_support import NONE
from ashley.inference.provider import ProviderFailed, ProviderRefused
from ashley.inference.router import RoutedInference
from ashley.inference.routes import Routes
from speech_support import MemoryLedger

CAPTURED = Path(__file__).with_name("image_captured")
JPEG = bytes.fromhex("ffd8ffe000104a464946") + b"\x00" * 20


def captured(name: str) -> Any:
    """A response the real provider gave (`image_captured/`), its image bytes swapped for `JPEG`."""
    return json.loads((CAPTURED / name).read_text())


@dataclass
class ScriptedMaker(ImageMaker):
    """Draws `JPEG`, or raises `error`; keeps the prompts it was asked."""

    label: str
    error: ProviderFailed | ProviderRefused | None = None
    asked: list[str] = field(default_factory=list[str])

    @property
    def name(self) -> str:
        return self.label

    def check_image_params(self, params: Mapping[str, object]) -> None:
        return None

    async def make(self, model: str, params: Mapping[str, object], prompt: str, aspect: Aspect,
                   timeout_s: float) -> Made:
        self.asked.append(prompt)
        if self.error is not None:
            raise self.error
        return Made(JPEG, "image/jpeg", Usage(10, 1000))


class Counted:
    """A household's count of pictures, settable."""

    def __init__(self, drawn: int = 0) -> None:
        self.drawn = drawn

    async def __call__(self, household_id: int, window_s: int) -> int:
        return self.drawn


def router(*makers: ImageMaker, drawn: int = 0, limit: int = 2, capped: bool = True,
           ledger: MemoryLedger | None = None) -> tuple[RoutedInference, MemoryLedger]:
    ledger = ledger or MemoryLedger()
    text: dict[Task, tuple[Route, ...]] = {t: (Route("none", "m", 1.0),) for t in get_args(Task)}
    routes = Routes(text, 300.0, image={"image": tuple(Route(m.name, f"{m.name}-model", 5.0) for m in makers)})
    cap = ImageCap(Counted(drawn), ImageLimit(limit, 86400)) if capped else None
    return RoutedInference(routes, makers, ledger, NONE, image_cap=cap), ledger

"""The Markdown shipped beside this package, per variant: `ashley.md`, `kinds/<kind>.md`, and overrides under
`variants/<variant>/` with the same names."""

from importlib import resources
from importlib.resources.abc import Traversable

from ..inference.model import DEFAULT_VARIANT


def _root() -> Traversable:
    return resources.files("ashley.persona")


def variants() -> list[str]:
    """`default`, then every directory under `variants/`, sorted."""
    found = _root() / "variants"
    named = sorted(d.name for d in found.iterdir() if d.is_dir()) if found.is_dir() else []
    return [DEFAULT_VARIANT] + [n for n in named if n != DEFAULT_VARIANT]


def read(variant: str, path: str) -> str | None:
    """The file at `path` for `variant`: its override when it has one, else the default's; None when neither exists."""
    parts = path.split("/")
    candidates = [_root().joinpath("variants", variant, *parts)] if variant != DEFAULT_VARIANT else []
    for f in [*candidates, _root().joinpath(*parts)]:
        if f.is_file():
            return f.read_text(encoding="utf-8").strip()
    return None

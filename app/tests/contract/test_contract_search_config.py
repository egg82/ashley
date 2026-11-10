"""`search_config.load`: the shipped `search.json` as a frozen `SearchConfig`, and ValueError for a missing key, an
unknown key, or a number that is not positive. The loader takes no argument, so the file it reads is swapped by
patching the reads of a file named `search.json`."""

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from ashley.tools import search_config
from ashley.tools.search_config import SearchConfig, load

SHIPPED = Path(search_config.__file__).parent / "search.json"
GOOD: dict[str, Any] = {"photon_url": "https://photon.komoot.io",
                        "timeout_s": 8, "web_results": 5, "snippet_chars": 300, "places_fetched": 15,
                        "places_results": 3, "bias_decimals": 2, "home_ttl_s": 86400}
NUMBERS = [k for k, v in GOOD.items() if not isinstance(v, str)]


def serve(monkeypatch: pytest.MonkeyPatch, data: dict[str, Any]) -> None:
    """Whatever reads `search.json` through pathlib gets `data`; every other file reads as before."""
    text = json.dumps(data)
    real_text, real_bytes = Path.read_text, Path.read_bytes

    def read_text(self: Path, *a: Any, **k: Any) -> str:
        return text if self.name == "search.json" else real_text(self, *a, **k)

    def read_bytes(self: Path) -> bytes:
        return text.encode() if self.name == "search.json" else real_bytes(self)

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)


def test_the_shipped_file_holds_the_contracts_values_and_loads() -> None:
    assert json.loads(SHIPPED.read_text()) == GOOD
    config = load()
    assert dataclasses.asdict(config) == GOOD
    assert isinstance(config, SearchConfig) and dataclasses.is_dataclass(config)


def test_the_config_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(load(), "web_results", 9)


def test_a_good_file_served_through_the_patch_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, {**GOOD, "web_results": 7})
    assert load().web_results == 7, "control: the patch is what load() reads"


@pytest.mark.parametrize("key", list(GOOD))
def test_a_missing_key_is_a_value_error(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    serve(monkeypatch, {k: v for k, v in GOOD.items() if k != key})
    with pytest.raises(ValueError):
        load()


def test_an_unknown_key_is_a_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, {**GOOD, "searxng_ulr": "typo"})
    with pytest.raises(ValueError):
        load()


@pytest.mark.parametrize("bad", [0, -1])
@pytest.mark.parametrize("key", NUMBERS)
def test_a_number_that_is_not_positive_is_a_value_error(monkeypatch: pytest.MonkeyPatch, key: str, bad: int) -> None:
    serve(monkeypatch, {**GOOD, key: bad})
    with pytest.raises(ValueError):
        load()

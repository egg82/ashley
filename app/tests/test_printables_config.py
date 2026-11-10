"""The Printables tunables (`printables.json`)."""

import json
from typing import Any

import pytest

from ashley.printables import config as printables_config

SHIPPED: dict[str, Any] = json.loads(printables_config.FILE.read_text())


def test_the_shipped_config_loads_with_its_hosts_lowercased() -> None:
    loaded = printables_config.load()
    assert loaded.file_hosts == frozenset({"files.printables.com"}) and loaded.results == SHIPPED["results"]


@pytest.mark.parametrize("change", [
    {"api_url": ""}, {"site_url": 3}, {"file_hosts": []}, {"file_hosts": ["", "a"]}, {"file_hosts": "files.printables.com"},
    {"timeout_s": 0}, {"download_timeout_s": True}, {"results": 0}, {"summary_chars": 1.5}, {"listed_files": -1},
    {"max_redirects": "3"}, {"extra": 1}, {"results": None}])
def test_a_bad_config_is_refused(change: dict[str, Any]) -> None:
    data = {k: v for k, v in {**SHIPPED, **change}.items() if v is not None}
    with pytest.raises(ValueError):
        printables_config.parse(data)


def test_a_config_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(ValueError):
        printables_config.parse([])

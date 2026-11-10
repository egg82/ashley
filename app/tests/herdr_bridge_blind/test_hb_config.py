"""The settings file the bridge refuses to start from."""

import json
from pathlib import Path

import pytest
from herdr_bridge.config import Config, ConfigError, load


def settings(tmp: Path, **change: object) -> Path:
    ca = tmp / "ca.pem"
    ca.write_text("x")
    body: dict[str, object] = {
        "host": "127.0.0.1",
        "port": 7843,
        "roots": [str(tmp)],
        "state_dir": str(tmp / "state"),
        "client_ca": str(ca),
        "herdr": "herdr",
        "start_timeout_ms": 90000,
    }
    body.update(change)
    path = tmp / "config.json"
    path.write_text(json.dumps(body))
    return path


def test_a_complete_file_loads_and_dumps_back_the_same(tmp_path: Path) -> None:
    config = load(settings(tmp_path))
    config.dump(tmp_path / "again.json")
    assert load(tmp_path / "again.json") == config
    assert config.roots == (str(tmp_path),)


def test_a_client_ca_that_is_not_a_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load(settings(tmp_path, client_ca=str(tmp_path / "absent.pem")))


@pytest.mark.parametrize("roots", [[], ["relative/dir"], ["/ok", "rel"], "/not/a/list", [5]])
def test_roots_must_be_a_non_empty_list_of_absolute_directories(tmp_path: Path, roots: object) -> None:
    with pytest.raises(ConfigError):
        load(settings(tmp_path, roots=roots))


def test_an_unknown_setting_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load(settings(tmp_path, allow_everything=True))


@pytest.mark.parametrize("missing", ["host", "port", "state_dir", "client_ca"])
def test_a_missing_required_setting_is_refused(tmp_path: Path, missing: str) -> None:
    path = settings(tmp_path)
    body = json.loads(path.read_text())
    del body[missing]
    path.write_text(json.dumps(body))
    with pytest.raises(ConfigError):
        load(path)


@pytest.mark.parametrize("raw", ["", "not json", "[]", "null"])
def test_a_file_that_is_not_an_object_is_refused(tmp_path: Path, raw: str) -> None:
    path = tmp_path / "config.json"
    path.write_text(raw)
    with pytest.raises(ConfigError):
        load(path)


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load(tmp_path / "absent.json")


def test_the_config_type_is_what_load_returns(tmp_path: Path) -> None:
    assert isinstance(load(settings(tmp_path)), Config)

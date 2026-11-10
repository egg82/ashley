"""Mail's tunables: the shipped file loads, and a missing, unknown or non-positive value is refused."""

import json

import pytest
from ashley.mail import config


def test_the_shipped_file_loads() -> None:
    shipped = config.load()
    assert shipped == config.MailConfig(**json.loads(config.FILE.read_text()))
    assert shipped.refresh_margin_s > 0 and shipped.search_max > 0 and shipped.timeout_s > 0


def _file(**changed: object) -> dict[str, object]:
    return {**json.loads(config.FILE.read_text()), **changed}


@pytest.mark.parametrize("data", [[], {}, _file(refresh_margin_s=0), _file(refresh_margin_s=1.5), _file(search_max=True),
                                  _file(body_chars=-1), _file(timeout_s=0), _file(timeout_s="1"), _file(extra=1)])
def test_a_bad_file_is_refused(data: object) -> None:
    with pytest.raises(ValueError):
        config.parse(data)


def test_a_missing_key_is_refused() -> None:
    data = _file()
    del data["search_max"]
    with pytest.raises(ValueError):
        config.parse(data)

"""`is_excluded`, and the shipped list of actions she is never offered: the announcements, and no control of the kiosk's."""

import pytest
from ashley.channels.kiosk.controls import ACTIONS
from ashley.tools import home_assistant_config
from ashley.tools.excluding import is_excluded


def test_a_name_matches_whole_or_after_its_domain_only() -> None:
    assert is_excluded("HassBroadcast", ("HassBroadcast",))
    assert is_excluded("x__HassBroadcast", ("HassBroadcast",))
    assert not is_excluded("HassBroadcastAll", ("HassBroadcast",))
    assert not is_excluded("xHassBroadcast", ("HassBroadcast",))


def test_the_shipped_list_excludes_the_satellites_announcements() -> None:
    excluded = home_assistant_config.load().excluded
    assert is_excluded("assist_satellite.announce", excluded)
    assert not is_excluded("light.turn_off", excluded)


def test_no_action_a_kiosk_control_may_take_is_excluded() -> None:
    excluded = home_assistant_config.load().excluded
    assert ACTIONS
    assert not [a for a in ACTIONS if is_excluded(a, excluded)]


@pytest.mark.parametrize("bad", [[], {}, {"excluded": "HassBroadcast"}, {"excluded": [""]}, {"excluded": [], "x": 1}, {"excluded": [], "reads": []}])
def test_a_malformed_config_is_refused(bad: object) -> None:
    with pytest.raises(ValueError):
        home_assistant_config.parse(bad)

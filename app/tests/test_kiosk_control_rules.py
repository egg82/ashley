"""The rules a list of controls is held to before it is stored: each light is in the house's catalogue and in its action's
domain, labels and keys are bounded, and a new control is given a key from its label."""

import pytest
from ashley.channels.kiosk.controls import MAX_CONTROLS, Control, ControlRefused, Wanted, validate

HOUSE = {"light.zq_hall": "light", "light.zq_porch": "light", "lock.zq_front": "lock", "scene.zq_night": "scene"}


def test_a_new_control_is_given_a_key_from_its_label_and_a_name_kept_as_given() -> None:
    got = validate([Wanted(None, " Hall light ", "light.turn_on", "light.zq_hall"),
                    Wanted("porch", "Porch off", "light.turn_off", "light.zq_porch")], HOUSE)
    assert got == (Control("hall-light", "Hall light", "light.turn_on", "light.zq_hall"),
                   Control("porch", "Porch off", "light.turn_off", "light.zq_porch"))


def test_two_new_controls_with_one_label_get_different_keys() -> None:
    got = validate([Wanted(None, "Hall", "light.turn_on", "light.zq_hall"),
                    Wanted(None, "Hall", "light.turn_off", "light.zq_hall")], HOUSE)
    assert [c.id for c in got] == ["hall", "hall-2"]


def test_a_new_key_never_takes_one_a_later_control_keeps() -> None:
    got = validate([Wanted(None, "Hall", "light.turn_on", "light.zq_hall"),
                    Wanted("hall", "Porch", "light.turn_off", "light.zq_porch")], HOUSE)
    assert [c.id for c in got] == ["hall-2", "hall"]


def test_a_label_of_no_letters_still_gets_a_key() -> None:
    assert validate([Wanted(None, "!!!", "light.turn_on", "light.zq_hall")], HOUSE)[0].id == "control"


def test_no_controls_is_a_valid_list() -> None:
    assert validate([], {}) == ()


REFUSED: list[tuple[list[Wanted], str]] = [
    ([Wanted(None, "Hall", "light.turn_on", "light.zq_nowhere")], "unknown_entity"),
    ([Wanted(None, "Hall", "light.turn_on", "lock.zq_front")], "unknown_entity"),
    ([Wanted(None, "Hall", "light.turn_on", "light")], "unknown_entity"),
    ([Wanted(None, "Night", "light.turn_on", "scene.zq_night")], "unknown_entity"),
    ([Wanted(None, "Hall", "scene.turn_on", "light.zq_hall")], "unknown_entity"),
    ([Wanted(None, " ", "light.turn_on", "light.zq_hall")], "bad_label"),
    ([Wanted(None, "x" * 41, "light.turn_on", "light.zq_hall")], "bad_label"),
    ([Wanted("Hall Light", "Hall", "light.turn_on", "light.zq_hall")], "bad_id"),
    ([Wanted("a", "A", "light.turn_on", "light.zq_hall"), Wanted("a", "B", "light.turn_on", "light.zq_hall")],
     "duplicate_id"),
    ([Wanted(None, "Hall", "light.turn_on", "light.zq_hall")] * (MAX_CONTROLS + 1), "too_many"),
]


@pytest.mark.parametrize(("wanted", "reason"), REFUSED)
def test_a_list_that_cannot_be_stored_is_refused_with_its_reason(wanted: list[Wanted], reason: str) -> None:
    with pytest.raises(ControlRefused) as refused:
        validate(wanted, HOUSE)
    assert refused.value.reason == reason


def test_the_most_controls_a_device_may_have_are_accepted() -> None:
    wanted = [Wanted(f"c{n}", f"Light {n}", "light.turn_on", "light.zq_hall") for n in range(MAX_CONTROLS)]
    assert len(validate(wanted, HOUSE)) == MAX_CONTROLS


def test_a_scene_is_accepted_with_its_own_action() -> None:
    got = validate([Wanted(None, "Night", "scene.turn_on", "scene.zq_night")], HOUSE)
    assert got == (Control("night", "Night", "scene.turn_on", "scene.zq_night"),)

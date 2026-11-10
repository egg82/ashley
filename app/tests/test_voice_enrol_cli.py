"""The CLI's `voice-enrol` and `voice-forget`: arming a satellite for a person of its household for N wakes within M
minutes, refusing a person of another household or bad numbers, and forgetting a person's prints with a count."""

import pytest
from ashley.channels.devices.__main__ import main
from contract.conversations_support import db_url as db_url, household, person
from contract.conversations_support import migrated_template as migrated_template, scalar
from voice_support import satellite_row


def cli(url: str, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setenv("DATABASE_URL", url)
    return main(list(argv))


def test_enrol_arms_the_device_for_the_wakes_and_minutes_given_or_the_defaults(
        db_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    alana, device = person(db_url, home), satellite_row(db_url, home).device.id
    assert cli(db_url, monkeypatch, "voice-enrol", str(device), str(alana)) == 0
    armed = "SELECT array[person_id, remaining, round(extract(epoch FROM until - now()) / 60)] FROM voice_enrolments"
    assert scalar(db_url, armed) == [alana, 6, 30]
    assert cli(db_url, monkeypatch, "voice-enrol", str(device), str(alana), "--wakes", "2", "--minutes", "5") == 0
    assert scalar(db_url, armed) == [alana, 2, 5]
    assert f"device {device} enrols person {alana} from its next 2 wakes within 5 minutes" in capsys.readouterr().out


@pytest.mark.parametrize(("extra", "status"), [(["--wakes", "0"], 2), (["--minutes", "0"], 2), ([], 1)])
def test_enrol_refuses_bad_numbers_and_a_person_of_another_household(
        db_url: str, monkeypatch: pytest.MonkeyPatch, extra: list[str], status: int) -> None:
    home, elsewhere = household(db_url), household(db_url, "away")
    device = satellite_row(db_url, home).device.id
    who = person(db_url, home) if extra else person(db_url, elsewhere)
    assert cli(db_url, monkeypatch, "voice-enrol", str(device), str(who), *extra) == status
    assert scalar(db_url, "SELECT count(*) FROM voice_enrolments") == 0


def test_forget_prints_how_many_prints_went(db_url: str, monkeypatch: pytest.MonkeyPatch,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    alana, device = person(db_url, home), satellite_row(db_url, home).device.id
    for _ in range(2):
        scalar(db_url, "INSERT INTO voiceprints (household_id, person_id, model, vector, device_id) "
                       "VALUES (%s, %s, 'titanet', '[1,0]', %s) RETURNING id", (home, alana, device))
    assert cli(db_url, monkeypatch, "voice-forget", str(alana)) == 0
    assert cli(db_url, monkeypatch, "voice-forget", str(alana)) == 0
    assert capsys.readouterr().out.splitlines() == [f"2 voiceprints of person {alana} forgotten",
                                                    f"0 voiceprints of person {alana} forgotten"]
    assert scalar(db_url, "SELECT count(*) FROM voiceprints") == 0

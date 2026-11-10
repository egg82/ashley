"""`shooter.shoot`: the line a look prints for a page: `MARK` and a JPEG that fits `max_bytes` (quality stepping down
until it does), or `FAILED` and a short reason (`not_ready` when the page never drew, `too_large` when no quality
fits); the page's address, a credential, is never in it."""

import base64

import pytest
from ashley.looks import shooter
from warm_blind_browser_support import PwError, Script, playwright
from warm_blind_support import LIMITS, PAGE_URL, TOKEN


def shot(script: Script, **limits: int) -> str:
    api, p = playwright(script)
    return shooter.shoot(api, p, PAGE_URL, {**LIMITS, **limits})


def test_a_page_that_fits_is_the_mark_and_its_jpeg() -> None:
    script = Script()
    line = shot(script)
    assert line.startswith(shooter.MARK)
    jpeg = base64.b64decode(line[len(shooter.MARK):])
    assert jpeg.startswith(bytes.fromhex("ffd8ff"))
    assert len(jpeg) <= LIMITS["max_bytes"]
    assert script.gotos == [PAGE_URL]


def test_the_first_quality_that_fits_is_the_one_used() -> None:
    script = Script(scale=20)
    shot(script, quality=80, max_bytes=2000)
    assert script.qualities == [80]


def test_quality_steps_down_until_the_picture_fits() -> None:
    script = Script(scale=20)
    line = shot(script, quality=80, max_bytes=1000)
    assert line.startswith(shooter.MARK)
    assert len(script.qualities) >= 2
    taken = [int(str(q)) for q in script.qualities]
    assert taken[0] == 80 and taken == sorted(taken, reverse=True) and len(set(taken)) == len(taken)
    assert len(base64.b64decode(line[len(shooter.MARK):])) <= 1000


def test_a_picture_over_the_limit_at_every_quality_is_too_large() -> None:
    line = shot(Script(scale=100_000), max_bytes=1000)
    assert line == shooter.FAILED + "too_large"


def test_a_picture_exactly_the_limit_fits() -> None:
    script = Script(scale=1)
    line = shot(script, quality=40, max_bytes=40)
    assert line.startswith(shooter.MARK)
    assert script.qualities == [40] and len(base64.b64decode(line[len(shooter.MARK):])) == 40


def test_a_picture_one_byte_over_at_the_last_quality_is_too_large() -> None:
    line = shot(Script(scale=1), quality=40, max_bytes=19)
    assert line == shooter.FAILED + "too_large"


def test_a_page_that_never_draws_is_not_ready() -> None:
    script = Script(ready=False)
    assert shot(script) == shooter.FAILED + "not_ready"
    assert script.qualities == []


def test_the_page_gets_ready_s_to_draw() -> None:
    script = Script()
    shot(script, ready_s=7)
    timeouts = [t for name, t in script.waits if name in ("selector", "function", "locator")]
    assert timeouts and all(t == 7000 for t in timeouts)


def test_a_browser_that_cannot_start_is_a_failure_that_is_not_an_answer() -> None:
    line = shot(Script(launch_error=PwError("no browser")))
    assert line.startswith(shooter.FAILED)
    assert line[len(shooter.FAILED):] not in ("not_ready", "too_large")


def test_a_failure_never_carries_the_address_or_its_token() -> None:
    line = shot(Script(goto_error=PwError(f"net::ERR_FAILED at {PAGE_URL}")))
    assert line.startswith(shooter.FAILED)
    assert PAGE_URL not in line and TOKEN not in line


def test_the_mark_line_never_carries_the_address(capfd: pytest.CaptureFixture[str]) -> None:
    line = shot(Script())
    out = capfd.readouterr()
    assert TOKEN not in line + out.out + out.err


def test_the_browser_is_closed_when_the_look_ends() -> None:
    for script in (Script(), Script(ready=False), Script(goto_error=PwError("x")), Script(scale=100_000)):
        shot(script)
        launched = [i for kind, i in script.events if kind == "launch"]
        closed = [i for kind, i in script.events if kind == "close"]
        assert launched == closed


def test_qualities_start_at_the_quality_and_only_go_down_never_under_one() -> None:
    for quality in (100, 80, 50, 3, 2, 1):
        steps = shooter.qualities(quality)
        assert steps[0] == quality
        assert steps == sorted(steps, reverse=True)
        assert all(1 <= s <= quality for s in steps)
    assert len(shooter.qualities(80)) >= 2
    assert min(shooter.qualities(80)) < 80



def test_the_picture_is_never_taller_than_max_height_nor_shorter_than_the_viewport() -> None:
    for page_height, expect in ((5000, LIMITS["max_height"]), (100, LIMITS["height"]), (1500, 1500)):
        script = Script(height=page_height)
        api, p = playwright(script)
        shooter.shoot(api, p, PAGE_URL, LIMITS)
        assert script.clips and all(c["height"] == expect and c["width"] == LIMITS["width"] for c in script.clips)

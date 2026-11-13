"""Plants each mutant of `automations_house_MUTANTS.txt` in a scratch copy of `app/`, one at a time, runs the suites
that carry the house's automations for her callers, and prints which survived. Run from `app/`:

    python tests/automations_house_mutants.py <scratch dir> [label ...]

Each plant is asserted to apply exactly once and the file is restored from the text read before planting."""

import shutil
import subprocess
import sys
from pathlib import Path

SUITES = ("tests/automation_blind", "tests/test_install_piece.py", "tests/test_bench_automations.py",
          "tests/test_workshop_install_routes.py", "tests/test_automations_house_pins.py")

H = "ashley/home_assistant/"
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    ("A1", H + "ha_house.py", "        for attempt in range(self._settings.entity_tries):", "        for attempt in range(1):"),
    ("A2", H + "ha_house.py", "if i.id == config_id and i.thing), None)", "if i.thing), None)"),
    ("A3", H + "ha_house.py", "            if thing is not None:\n                return thing",
     "            if thing is not None:\n                return None"),
    ("A4", H + "ha_changes.py", 'quote(made, safe=""), f"write {kind}"', 'quote(made + "x", safe=""), f"write {kind}"'),
    ("A5", H + "ha_house.py", '        service = "turn_on" if enabled else "turn_off"',
     '        service = "turn_off" if enabled else "turn_on"'),
    ("A6", H + "ha_house.py", '{"entity_id": thing}', "{}"),
    ("A7", H + "ha_house.py", "        except HouseRejected as e:\n            raise HouseUnavailable",
     "        except HouseRejected as e:\n            return\n            raise HouseUnavailable"),
    ("A8", H + "ha_changes.py", 'enabled = text(state.get("state")) == "on" if', "enabled = True if"),
    ("A9", H + "ha_changes.py", '                      moment(attributes.get("last_triggered")))', "                      None)"),
    ("A10", H + "ha_changes.py", " or thing, thing, enabled,", " or thing, None, enabled,"),
    ("A11", H + "ha_changes.py", 'text(attributes.get("friendly_name")) or thing, thing', "thing, thing"),
    ("A12", H + "ha_changes.py", 'if _config_id(kind, s) or kind == "automation")', "if _config_id(kind, s))"),
    ("A13", H + "ha_changes.py", "        return obj(got) if is_object(got) else None\n\n    async def write_config",
     "        return obj(got)\n\n    async def write_config"),
    ("A14", H + "ha_rest.py", "        if got.status_code in missing:\n            return False",
     "        if got.status_code in missing:\n            return True"),
    ("A15", H + "ha_rest.py", "        if got.status_code == 400:\n            raise HouseRejected(_message(got))\n        return _json",
     "        return _json"),
    ("A16", H + "ha_rest.py", "    if got.status_code // 100 != 2:", "    if got.status_code // 100 == 9:"),
    ("A17", H + "house.py", "    except HouseUnavailable:\n        return None\n    return any",
     "    except HouseUnavailable:\n        return False\n    return any"),
    ("A18", H + "house.py", "return any(a.name == name for a in offered) if offered", "return True if offered"),
    ("A19", H + "ha_changes.py", "ConfigItem(_config_id(kind, state) or None,", "ConfigItem(None,"),
    ("A20", H + "ha_changes.py", '        return await self._rest.delete(_FILES[kind] + quote(config_id, safe=""), f"delete {kind}")',
     "        return True"),
    ("A21", H + "ha_rest.py", '            raise HouseUnavailable(f"{step}: {type(e).__name__}") from e', "            raise"),
)


def plant(app: Path, label: str, rel: str, old: str, new: str) -> str:
    path = app / rel
    text = path.read_text()
    found = text.count(old)
    assert found == 1, f"{label}: anchor found {found} times in {rel}"
    path.write_text(text.replace(old, new, 1))
    assert new in path.read_text(), f"{label}: plant not written"
    return text


def suites(app: Path) -> str:
    """"green", "red" (a test failed; under xdist `-x` exits 2 with "stopping after"), or "broken" for any other run,
    which is not a kill."""
    got = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-n", "2", "-p", "no:cacheprovider", *SUITES],
                         cwd=app, capture_output=True, text=True, timeout=300)
    if got.returncode == 0:
        return "green"
    failed = got.returncode == 1 or (got.returncode == 2 and "stopping after 1 failures" in got.stdout)
    return "red" if failed else "broken"


def skip_top_web(directory: str, names: list[str]) -> set[str]:
    top = {"web"} if Path(directory).name == "app" else set[str]()
    return top | {n for n in names if n in ("node_modules", "__pycache__", ".pytest_cache")}


def main() -> None:
    scratch = Path(sys.argv[1]).resolve()
    wanted = set(sys.argv[2:])
    app = scratch / "app"
    if not app.exists():
        shutil.copytree(Path(__file__).resolve().parents[1], app, ignore=skip_top_web)
    assert suites(app) == "green", "the suites are not green on the unplanted copy"
    survived: list[str] = []
    for label, rel, old, new in MUTANTS:
        if wanted and label not in wanted:
            continue
        before = plant(app, label, rel, old, new)
        try:
            status = suites(app)
        finally:
            (app / rel).write_text(before)
        assert status != "broken", f"{label}: a broken run, not a kill"
        print(label, "killed" if status == "red" else "SURVIVED", flush=True)
        if status == "green":
            survived.append(label)
    print("survived:", " ".join(survived) or "none")


if __name__ == "__main__":
    main()

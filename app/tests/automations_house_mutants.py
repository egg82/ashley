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

R = "ashley/home_assistant/rest_automations.py"
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    ("R1", R, "        for attempt in range(self._config.entity_tries):", "        for attempt in range(1):"),
    ("R2", R, "if a.automation_id == automation_id), None)", "), None)"),
    ("R3", R, "            if entity is not None:\n                return entity",
     "            if entity is not None:\n                return None"),
    ("R4", R, '_CONFIG + quote(automation_id, safe=""), "write", dict(config))',
     '_CONFIG + quote(automation_id + "x", safe=""), "write", dict(config))'),
    ("R5", R, '        service = "turn_on" if enabled else "turn_off"', '        service = "turn_off" if enabled else "turn_on"'),
    ("R6", R, '{"entity_id": entity_id})', "{})"),
    ("R7", R, "        _json(got, service)", "        pass"),
    ("R8", R, 'state.get("state") == "on",', "True,"),
    ("R9", R, "                      _moment(attributes.get(\"last_triggered\")))", "                      None)"),
    ("R10", R, "    return Automation(automation_id if isinstance(automation_id, str) else None, entity,",
     "    return Automation(None, entity,"),
    ("R11", R, "                      alias if isinstance(alias, str) else entity,", "                      entity,"),
    ("R12", R, "    automation_id = attributes.get(\"id\")\n",
     "    automation_id = attributes.get(\"id\")\n    if not isinstance(automation_id, str):\n        return None\n"),
    ("R13", R, "        if got.status_code == 404:\n            return None\n        raw = _object",
     "        raw = _object"),
    ("R14", R, "        if got.status_code in (400, 404):\n            return False", "        if got.status_code in (400, 404):\n            return True"),
    ("R15", R, "        if got.status_code == 400:\n            raise AutomationRejected(_message(got))\n", ""),
    ("R16", R, "    if got.status_code // 100 != 2:", "    if got.status_code // 100 == 9:"),
    ("R17", R, "        except AutomationsUnavailable:\n            return None", "        except AutomationsUnavailable:\n            return False"),
    ("R18", R, "        return service in offered[domain] if domain in offered else False", "        return True"),
    ("R19", R, "        return sorted((a for a in found if a is not None), key=lambda a: a.entity_id)",
     "        return [a for a in found if a is not None]"),
    ("R20", R, '        got = await self._send("DELETE", _CONFIG + quote(automation_id, safe=""), "delete")',
     '        return True\n        got = await self._send("DELETE", _CONFIG + quote(automation_id, safe=""), "delete")'),
    ("R21", R, "            raise AutomationsUnavailable(f\"{step}: {type(e).__name__}\") from e", "            raise"),
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

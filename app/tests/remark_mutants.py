"""Plants each wrong implementation below in a scratch copy of `app/`, one at a time, runs the remark suites, and
prints which survived. Run from `app/`:

    python tests/remark_mutants.py <scratch dir> [label ...]

A plant that does not apply exactly once is reported as not planted; a kill is exit 1 with a FAILED line."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

SUITES = ("tests/test_remark_decision.py", "tests/test_discord_remark.py", "tests/test_remarks_store.py")

MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    ("cap >= to >", "ashley/initiative/remark.py", "chance.sent >= rates.per_day", "chance.sent > rates.per_day"),
    ("roll ignored", "ashley/initiative/remark.py", "    if not rolls(chance.seed, rates):\n        return \"rolled_out\"\n", ""),
    ("typing_known ignored", "ashley/initiative/remark.py", " or not chance.typing_known:", ":"),
    ("typing < to <=", "ashley/initiative/remark.py", "chance.since_typed_s < rates.typing_within_s", "chance.since_typed_s <= rates.typing_within_s"),
    ("night ignored", "ashley/initiative/remark.py", "    if at_night(chance.hour, weights):\n        return \"night\"\n", ""),
    ("no casefold", "ashley/initiative/remark.py", "line.casefold()", "line"),
    ("repeat ignored", "ashley/initiative/initiative.py", " and not repeats(line, chance)", ""),
    ("speaks: remark branch gone", "ashley/channels/unprompted.py", "    if inbound.remark is not None:\n        return services", "    if False:\n        return services"),
    ("phone not excluded", "ashley/channels/to_phone.py", " and inbound.remark is None", ""),
    ("stranger allowed", "ashley/channels/discord/remark.py", "person is None or person.household_id != server.device.household_id", "person is None"),
    ("tools offered", "ashley/channels/discord/remark.py", "tools_only=(), note=NOTE", "tools_only=None, note=NOTE"),
    ("settle body always", "ashley/channels/discord/bot.py", "None if out.says == \"none\" else out.body", "out.body"),
    ("count quiet too", "ashley/channels/postgres_remarks.py", "AND (NOT settled OR line IS NOT NULL)", ""),
    ("said per person", "ashley/channels/postgres_remarks.py", "AND line IS NOT NULL \"\n                    \"ORDER BY claimed_at\", (household_id, said_since))", "AND line IS NOT NULL AND person_id = %s \"\n                    \"ORDER BY claimed_at\", (household_id, said_since, person_id))"),
    ("checkpoint drops remark", "ashley/channels/checkpoint.py", "remark=None if remark is None else _remark(remark)", "remark=None"),
    ("day window wrong", "ashley/channels/discord/remark.py", "now - timedelta(seconds=DAY_S)", "now - timedelta(seconds=2 * DAY_S)"),
)


def main(scratch: Path, only: list[str]) -> list[str]:
    survived: list[str] = []
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    for name, path, old, new in MUTANTS:
        if only and name not in only:
            continue
        copy = scratch / "app"
        shutil.rmtree(copy, ignore_errors=True)
        shutil.copytree(Path.cwd(), copy, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "build"))
        planted = copy / path
        text = planted.read_text()
        if text.count(old) != 1:
            print(f"NOT PLANTED ({text.count(old)}) {name}")
            survived.append(name)
            continue
        planted.write_text(text.replace(old, new))
        run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "-n", "0", *SUITES],
                             cwd=copy, env=env, capture_output=True, text=True)
        failed = [line for line in run.stdout.splitlines() if line.startswith("FAILED")]
        if run.returncode == 1 and failed:
            print(f"KILLED   {name}: {failed[0]}")
        else:
            print(f"SURVIVED {name} (exit {run.returncode})")
            survived.append(name)
    shutil.rmtree(scratch / "app", ignore_errors=True)
    return survived


if __name__ == "__main__":
    left = main(Path(sys.argv[1]), sys.argv[2:])
    print("survivors:", left)
    sys.exit(1 if left else 0)

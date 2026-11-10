"""Write `openapi.json`, the committed contract the web client's types are generated from. Run from `app/`:
`python tools/export_openapi.py`. `tests/test_contract.py` fails when the committed file differs from this output."""

import json
import sys
from pathlib import Path
from typing import Any

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
from ashley.main import create_app
from ashley.settings import Settings

SPEC_FILE = APP / "openapi.json"


def build_spec() -> dict[str, Any]:
    """The spec of the app as the factory builds it; no database is contacted."""
    return create_app(Settings(database_url="", build_version="dev")).openapi()


def render(spec: dict[str, Any]) -> str:
    return json.dumps(spec, indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    SPEC_FILE.write_text(render(build_spec()), encoding="utf-8")
    print(f"wrote {SPEC_FILE.name}")

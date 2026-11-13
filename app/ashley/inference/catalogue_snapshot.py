"""The catalogue's first layer: models.dev's list as it was when the image was built, so a new deployment prices calls
before its first fetch. The image build runs `python -m ashley.inference.catalogue_snapshot <path>`, which fetches the
list (`catalogue_config`'s url, a few tries), reads it as the refresh would and writes it with the time it was taken;
a list that cannot be fetched or read fails the build. The running app reads it from `SNAPSHOT`."""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx2

from . import catalogue_config, models_dev
from .catalogue_config import CatalogueConfig
from .catalogue_model import Catalogue, catalogue_from_json, catalogue_to_json

SNAPSHOT = Path("/opt/ashley/catalogue/models.json")
_TRIES = 3


async def fetch(config: CatalogueConfig, http: httpx2.AsyncClient) -> models_dev.Read:
    """models.dev's list, read. Raises httpx2's errors for a failed request or a status that is not 2xx, ValueError
    for a body that does not read."""
    response = await http.get(config.url, timeout=config.timeout_s)
    response.raise_for_status()
    return models_dev.parse(json.loads(response.content))


def load(path: Path = SNAPSHOT) -> tuple[Catalogue, datetime] | None:
    """The snapshot and when it was taken; None when there is no file (a process outside the image). Raises ValueError
    for a file that does not read: the image is broken."""
    if not path.exists():
        return None
    raw: dict[str, object] = json.loads(path.read_text())
    if set(raw) != {"taken_at", "catalogue"}:
        raise ValueError(f"{path}: expected taken_at and catalogue")
    return catalogue_from_json(raw["catalogue"]), datetime.fromisoformat(str(raw["taken_at"]))


def write(path: Path, catalogue: Catalogue, taken_at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"taken_at": taken_at.isoformat(), "catalogue": catalogue_to_json(catalogue)}))


async def main(out: Path) -> int:
    config = catalogue_config.load()
    async with httpx2.AsyncClient(follow_redirects=False) as http:
        for attempt in range(1, _TRIES + 1):
            try:
                read = await fetch(config, http)
            except (httpx2.HTTPError, ValueError) as e:
                print(f"catalogue snapshot: try {attempt} failed: {type(e).__name__}", file=sys.stderr)
                await asyncio.sleep(attempt * 15)
                continue
            write(out, read.catalogue, datetime.now(UTC))
            print(f"catalogue snapshot: providers={len(read.catalogue.providers)} "
                  f"models={read.catalogue.model_count()} skipped={read.skipped}")
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(Path(sys.argv[1]))))

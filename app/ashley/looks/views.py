"""The sides of a model she may ask `bench_look` to see it from: the ids in `views.json`, each a camera preset of the
look page (`app/web/src/rooms/workshop/solid/views.ts`, whose test checks the two agree)."""

import json
from pathlib import Path

VIEWS: tuple[str, ...] = tuple(str(v) for v in json.loads(Path(__file__).with_name("views.json").read_text()))

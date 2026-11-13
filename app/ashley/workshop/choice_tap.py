"""A person's tap on one of a choice row's options (`api.bench_choices`): the measurements body with that row set, as
theirs. Pure."""

import json
from typing import Any, Literal

from . import measurements

Untapped = Literal["no_row", "off_options"]


def tapped(body: str, name: str, value: str) -> str | Untapped:
    """`body`, a measurements piece's, with its choice row `name` set to `value` by the person: a value it did not hold
    becomes `stated`; the value it held becomes `accepted` when it was `guessed`, and is otherwise left as it was. A row
    whose source changes loses its `turn`, `piece` and `ref`, which cited where the old source came from. `body` itself
    when nothing changes. `no_row` when `body` holds no choice row `name`, `off_options` when `value` is not one of the
    row's options (a row with none takes no tap)."""
    row = next((r for r in measurements.items_of(body) or () if isinstance(r, measurements.Choice) and r.name == name),
               None)
    if row is None:
        return "no_row"
    if value not in row.options:
        return "off_options"
    source = "stated" if value != row.value else "accepted" if row.source == measurements.GUESSED else row.source
    if value == row.value and source == row.source:
        return body
    loaded: dict[str, Any] = json.loads(body)
    for item in loaded["items"]:
        if item.get("kind") == measurements.CHOICE and item["name"] == name:
            for cited in ("turn", "piece", "ref"):
                item.pop(cited, None)
            item.update(value=value, source=source)
    return json.dumps(loaded, ensure_ascii=False)

"""One key=value line per event on stdout, which Alloy ships to Loki. A field is an id, a count, a kind or a duration."""

import sys
from datetime import UTC, datetime


def emit(event: str, **fields: object) -> None:
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    rest = " ".join(f"{k}={v}" for k, v in fields.items())
    print(f"ts={stamp} level=info logger=keeper event={event} {rest}".rstrip(), file=sys.stdout, flush=True)

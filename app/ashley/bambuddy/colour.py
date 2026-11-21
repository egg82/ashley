"""Bambuddy writes a colour as hex with or without an alpha byte and with or without a leading `#`."""

import re

_HEX = re.compile(r"#?([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?")


def hex_of(text: str | None) -> str | None:
    """`text` as "#RRGGBB", None when it is not a hex colour (an empty slot writes `00000000`, which is black and kept)."""
    found = _HEX.fullmatch(text) if text else None
    return None if found is None else "#" + found.group(1).upper()

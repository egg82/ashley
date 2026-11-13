"""What code shows beside her reply on Discord: one separate message of Discord subtext (`-# `, small and grey, so it reads
as the app's and not as her), sent after her chunks and never counted in `max_messages`."""

from ...conversations.model import Receipt, Receipts
from ...tools import outside_config
from .config import Config

_WORDS = outside_config.load()
SUBTEXT = "-# "
LIMIT = 2000


def receipt_lines(receipts: Receipts | None, config: Config) -> str | None:
    """The message for `receipts`: a line for each change that ran, then each call waiting with its summary in full, and
    last a line saying to answer yes to go ahead when any waits. Every line begins `-# `. None when there are no
    receipts, or none but the bench page's choice rows (`Receipts.facts`). Cut, with its last line kept whole, to fit one
    Discord message."""
    if receipts is None or not (receipts.done or receipts.held):
        return None
    lines = [*(_line(_WORDS.done_label, r, None) for r in receipts.done),
             *(_line(_WORDS.held_label, r, r.detail) for r in receipts.held)]
    return _fitted("\n".join(lines), f"{SUBTEXT}{config.held_footer}" if receipts.held else None)


def _line(label: str, receipt: Receipt, detail: str | None) -> str:
    said = f"{receipt.headline}: {detail}" if detail else receipt.headline
    return f"{SUBTEXT}{label} {_oneline(said)}" + (f" ({_oneline(receipt.why)})" if receipt.why else "")


def _oneline(text: str) -> str:
    return " ".join(text.split())


def _fitted(body: str, footer: str | None) -> str:
    whole = body if footer is None else f"{body}\n{footer}"
    if len(whole) <= LIMIT:
        return whole
    room = LIMIT - (0 if footer is None else len(footer) + 1) - 1
    return f"{body[:room].rstrip()}…" + ("" if footer is None else f"\n{footer}")

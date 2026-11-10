"""The settings of a turn that has read outside words, data in `outside.json` beside this module: how long held calls can
still be agreed (`proposal_ttl_s`), the most calls one turn holds (`max_calls`), the most characters of JSON one held
call's arguments may take (`max_argument_chars`), how long the record of what ran without asking is kept
(`actions_keep_s`) and how long a list a tainted turn wrote counts as outside (`writes_keep_s`), how many of the person's
latest messages (`words_turns`) and how many characters of each (`words_chars`) the action judge reads, the arguments of each tool
the record of what ran without asking may name (`summary_arguments`: ones that hold an action or a folder, never text),
and the text she and the person read: the headline of a change whose tool has no label (`unlabelled`), the words that head a change that ran and one that waits where receipts are small text
(`done_label`, `held_label`), the line that
carries receipts into her history (`history_*`), what a tap on Agree stores as the person's turn (`agreed_turn`), and
the words her history gives each agreed call's outcome (`agreed_ran`, `agreed_failed`, `not_run`) in the line for an
agreeing turn (`history_agreed`, `history_agreed_interrupted`)."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ..home_assistant.ha_json import names, obj

FILE = Path(__file__).with_name("outside.json")
_NUMBERS = ("proposal_ttl_s", "max_calls", "max_argument_chars", "actions_keep_s", "writes_keep_s", "words_turns",
            "words_chars")
_SECONDS = ("proposal_ttl_s", "actions_keep_s", "writes_keep_s")
_TEXTS = ("held", "needs_private", "too_long", "too_many", "agreeing_tainted", "nothing_to_carry_out", "not_run",
          "unavailable",
          "carry_out_description", "unlabelled", "done_label", "held_label", "history_line", "history_done", "history_held", "unknown_recipient",
          "no_words", "why_held", "why_ran", "agreed_turn", "agreed_ran", "agreed_failed", "history_agreed",
          "history_agreed_interrupted")


@dataclass(frozen=True)
class OutsideConfig:
    proposal_ttl_s: float
    max_calls: int
    max_argument_chars: int
    actions_keep_s: float
    writes_keep_s: float
    words_turns: int
    words_chars: int
    summary_arguments: Mapping[str, tuple[str, ...]]
    held: str
    needs_private: str
    too_long: str
    too_many: str
    agreeing_tainted: str
    nothing_to_carry_out: str
    not_run: str
    unavailable: str
    carry_out_description: str
    unlabelled: str
    done_label: str
    held_label: str
    history_line: str
    history_done: str
    history_held: str
    unknown_recipient: str
    no_words: str
    why_held: str
    why_ran: str
    agreed_turn: str
    agreed_ran: str
    agreed_failed: str
    history_agreed: str
    history_agreed_interrupted: str


def load() -> OutsideConfig:
    """The settings shipped in `outside.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(raw: object) -> OutsideConfig:
    """OutsideConfig from JSON already parsed. Raises ValueError unless the keys are exactly the numbers and texts, each
    number positive (the counts integers) and each text non-empty."""
    top = obj(raw)
    if not isinstance(raw, dict) or set(top) != {*_NUMBERS, *_TEXTS, "summary_arguments"}:
        raise ValueError(f"outside.json has exactly {', '.join((*_NUMBERS, *_TEXTS, 'summary_arguments'))}")
    for key in _NUMBERS:
        v = top[key]
        whole = key not in _SECONDS
        if isinstance(v, bool) or not isinstance(v, int | float) or v <= 0 or (whole and not isinstance(v, int)):
            raise ValueError(f"{key}: expected a positive number")
    for key in _TEXTS:
        text = top[key]
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{key}: expected text")
    return OutsideConfig(float(_number(top["proposal_ttl_s"])), int(_number(top["max_calls"])),
                         int(_number(top["max_argument_chars"])), float(_number(top["actions_keep_s"])),
                         float(_number(top["writes_keep_s"])), int(_number(top["words_turns"])),
                         int(_number(top["words_chars"])), _summary_arguments(top["summary_arguments"]),
                         *(str(top[k]) for k in _TEXTS))


def _summary_arguments(raw: object) -> Mapping[str, tuple[str, ...]]:
    return {tool: names(arguments) for tool, arguments in obj(raw).items()}


def _number(value: object) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("expected a number")
    return value


def keeps() -> tuple[float, float]:
    """The seconds the record keeps what ran without asking and a list a tainted turn wrote, as shipped."""
    shipped = load()
    return shipped.actions_keep_s, shipped.writes_keep_s

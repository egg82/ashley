"""The pronunciation lexicon (`decisions.md`, "Spoken words differ from written ones"): real spellings the voice says
wrong, mapped to spellings it says right. A household's own words are `lexicons.Lexicons`' to read."""

import re
from collections.abc import Mapping
from typing import Literal

WORD = re.compile(r"\w[\w'-]*")
MAX_LENGTH = 64
Refusal = Literal["not_a_word", "blank_spelling", "too_long"]


def refusal(real: str, spoken: str) -> Refusal | None:
    """Why `real` to `spoken` is not an entry: `not_a_word` (a key that is not one word-like token), `blank_spelling`,
    or `too_long`; None when it is one."""
    if WORD.fullmatch(real) is None:
        return "not_a_word"
    if not spoken.strip():
        return "blank_spelling"
    return "too_long" if len(real) > MAX_LENGTH or len(spoken) > MAX_LENGTH else None


class Lexicon:
    """`respell(text)` replaces each whole word that is a key, matched case-sensitively, with its value; anything else
    is unchanged. Raises ValueError on construction for an entry `refusal` names."""

    def __init__(self, words: Mapping[str, str]) -> None:
        for real, spoken in words.items():
            why = refusal(real, spoken)
            if why is not None:
                raise ValueError(f"lexicon entry {real!r} is refused: {why}")
        self._words = dict(words)
        alternatives = "|".join(re.escape(w) for w in sorted(self._words, key=len, reverse=True))
        self._pattern = re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)") if self._words else None

    def respell(self, text: str) -> str:
        if self._pattern is None:
            return text
        return self._pattern.sub(lambda m: self._words[m.group(0)], text)


EMPTY = Lexicon({})

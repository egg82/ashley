"""The wire models of the spoken routes (`api.spoken`): what a transcript route answers and the limits the page records within."""

from pydantic import BaseModel


class Transcript(BaseModel):
    """What was heard in one spoken utterance, in real spellings; empty when nothing was said. The page sends it as a
    typed message, so a spoken turn is a typed one on the same thread."""

    text: str


class SpokenLimits(BaseModel):
    """Recording stops at `max_ms`, or after `speech_ms` of speech then `silence_ms` of quiet (speech: RMS >= `quiet_rms`).
    Her spoken answer to an utterance can be fetched for `voice_s` seconds."""

    max_ms: int
    speech_ms: int
    silence_ms: int
    quiet_rms: float
    voice_s: int

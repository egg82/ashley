"""When has the person stopped talking: a state machine over 10 ms speech probabilities, its timings data
(`config.EndOfSpeech`). Pure, so a test feeds it numbers instead of audio."""

from typing import Literal

from .config import EndOfSpeech

FRAME_MS = 10

State = Literal["waiting", "speaking", "ended"]
"""`waiting` for speech to start, `speaking` once it has, `ended` once it stopped or ran too long (final)."""


class Utterance:
    """`frame(probability)` takes one 10 ms frame and answers the state after it. `waiting` becomes `speaking` once
    `speech_ms` of frames above `start_probability` have come, the count starting again only after `start_gap_ms` of
    frames at or below it in a row; `speaking` becomes `ended` after `silence_ms` of frames at or below
    `speech_probability` in a row; any state becomes `ended` once `max_utterance_ms` of frames have been taken. A
    negative probability (the VAD still warming up, about its first 700 ms) counts as non-speech."""

    def __init__(self, timings: EndOfSpeech) -> None:
        self._t = timings
        self._elapsed = 0
        self._run = 0
        self._gap = 0
        self.state: State = "waiting"

    def frame(self, probability: float) -> State:
        if self.state == "ended":
            return self.state
        self._elapsed += FRAME_MS
        if self.state == "waiting":
            self._wait(probability > self._t.start_probability)
        else:
            self._run = 0 if probability > self._t.speech_probability else self._run + FRAME_MS
            if self._run >= self._t.silence_ms:
                self.state = "ended"
        if self._elapsed >= self._t.max_utterance_ms:
            self.state = "ended"
        return self.state

    def _wait(self, speech: bool) -> None:
        if speech:
            self._run, self._gap = self._run + FRAME_MS, 0
        else:
            self._gap += FRAME_MS
            if self._gap >= self._t.start_gap_ms:
                self._run, self._gap = 0, 0
        if self._run >= self._t.speech_ms:
            self.state, self._run = "speaking", 0

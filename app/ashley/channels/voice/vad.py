"""Speech probability per 10 ms of 16 kHz 16-bit mono PCM, from microVAD (`pymicro_vad`, the VAD Home Assistant's own
Assist pipeline uses), cut from chunks of any size."""

from typing import Protocol

from pymicro_vad import MicroVad

FRAME_BYTES = 320   # 10 ms of 16 kHz, 16-bit, mono


class Detector(Protocol):
    """What scores one 10 ms frame: a probability in [0, 1], or negative while it is still warming up."""

    def process_10ms(self, audio: bytes) -> float: ...


def micro_vad() -> Detector:
    """A fresh microVAD, warming up from silence."""
    return MicroVad()


class Frames:
    """`probabilities(chunk)` scores each whole 10 ms frame the chunk completes, keeping any remainder for the next
    chunk. One per utterance: the detector carries state across frames."""

    def __init__(self, detector: Detector) -> None:
        self._detector = detector
        self._pending = b""

    def probabilities(self, chunk: bytes) -> list[float]:
        data = self._pending + chunk
        whole = len(data) - len(data) % FRAME_BYTES
        self._pending = data[whole:]
        return [self._detector.process_10ms(data[i:i + FRAME_BYTES]) for i in range(0, whole, FRAME_BYTES)]

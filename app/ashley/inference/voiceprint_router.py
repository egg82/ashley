"""The voiceprint half of `RoutedInference`: the task's routes in order, each call recorded in the spend ledger.
Contract: `Inference.voiceprint`."""

from .inference import InferenceUnavailable
from .model import Usage
from .provider import ProviderFailed
from .roster import Roster
from .speech import AudioFormat
from .voiceprint import Voiceprint, VoiceprintTask
from .voiceprint_provider import VoiceEmbedder

TASK: VoiceprintTask = "voiceprint"


class VoiceprintCalls:
    def __init__(self, roster: Roster) -> None:
        self._roster = roster

    async def warm(self) -> None:
        for route, provider in self._roster.candidates(TASK, VoiceEmbedder):
            await self._roster.warm(TASK, route, provider.warm(route.model, route.params, route.timeout_s))
            return

    async def voiceprint(self, format: AudioFormat, pcm: bytes, conversation_id: int | None) -> Voiceprint:
        if not pcm or len(pcm) % format.frame_bytes:
            raise ValueError("a voiceprint takes audio of at least one whole frame")
        audio_ms = format.duration_ms(len(pcm))
        usage = Usage(0, 0, audio_ms=audio_ms)
        for route, provider in self._roster.candidates(TASK, VoiceEmbedder):
            started = self._roster.clock()
            try:
                vector = await provider.voiceprint(route.model, route.params, pcm, format, route.timeout_s)
            except ProviderFailed as e:
                await self._roster.record(TASK, route, e.failure, usage, started, {"audio_ms": audio_ms},
                                          conversation_id, str(e))
                self._roster.failed(route, e.failure)
                continue
            await self._roster.record(TASK, route, "ok", usage, started, {"audio_ms": audio_ms}, conversation_id)
            return Voiceprint(tuple(vector), route.model, audio_ms)
        raise InferenceUnavailable(f"no route answered for task {TASK}")

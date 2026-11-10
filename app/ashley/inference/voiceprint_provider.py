"""What a voiceprint provider is (Strategy, beside `Embedder` and the speech providers): a way to turn one utterance's
audio into a vector that says how the voice sounds. `routes.parse` rejects a `voiceprint` route whose provider is not a
`VoiceEmbedder`. Only `RoutedInference` calls it.

Failures are `provider.ProviderFailed`, as for text; a voice embedder never raises `ProviderRefused`."""

from abc import abstractmethod
from collections.abc import Mapping

from .provider import Wired
from .speech import AudioFormat


class VoiceEmbedder(Wired):
    @abstractmethod
    def check_voiceprint_params(self, params: Mapping[str, object]) -> None:
        """Raises ValueError naming the first parameter this provider does not take for voiceprints or a value it would
        reject. Called once per `voiceprint` route when the routes load."""

    @abstractmethod
    async def voiceprint(self, model: str, params: Mapping[str, object], pcm: bytes, format: AudioFormat,
                         timeout_s: float) -> list[float]:
        """One vector of unit length for the voice in `pcm`, a non-empty whole number of frames in `format`; giving up
        after `timeout_s` with no retry of its own. A format the provider does not take fails the call `error`.
        Raises ProviderFailed; never anything else."""

    async def warm(self, model: str, params: Mapping[str, object], timeout_s: float) -> None:
        """Do now what the first `voiceprint` of `model` would otherwise do first (load the model), so that call starts
        sooner; nothing billed. This default has nothing to prepare. Raises ProviderFailed; never anything else."""
        return None

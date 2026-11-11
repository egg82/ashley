"""What a speech provider is (Strategy, beside `Provider`): a way to turn audio into words, or words into audio. A
provider declares what it can do by being a `Transcriber`, a `Speaker`, or both, and `routes.parse` rejects a route
whose provider cannot do the route's task. Only `RoutedInference` calls them.

Failures are `provider.ProviderFailed`, as for text; a speech provider never raises `ProviderRefused`."""

from abc import abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass

from .provider import Wired
from .speech import AudioFormat


@dataclass(frozen=True)
class SpeechStream:
    """Audio the provider has started producing: `chunks` begins with bytes already received, and raises
    `ProviderFailed` if the provider breaks off afterwards. `close` releases the connection and may be awaited more
    than once, whether or not `chunks` was read to its end."""

    media_type: str
    chunks: AsyncIterator[bytes]
    close: Callable[[], Awaitable[None]]


class Transcriber(Wired):
    @abstractmethod
    def check_transcribe_params(self, params: Mapping[str, object]) -> None:
        """Raises ValueError naming the first parameter this provider does not take for transcription or a value it
        would reject. Called once per `transcribe` route when the routes load."""

    @abstractmethod
    async def transcribe(self, model: str, params: Mapping[str, object], format: AudioFormat,
                         chunks: AsyncIterator[bytes], timeout_s: float, language: str | None = None) -> str:
        """The words in the PCM `chunks` (in `format`), read to their end, spoken in `language` (ISO 639-1) when one is
        given, which wins over a `language` param of the route. A streaming provider sends each chunk as it
        arrives; one that needs the whole utterance reads it first. `timeout_s` bounds connecting and, once the
        audio has ended, waiting for the words; it never bounds waiting for `chunks`. The text is as the provider
        returned it. An exception raised by `chunks` itself may surface as a `ProviderFailed`.
        Raises ProviderFailed; never anything else."""


class Speaker(Wired):
    @abstractmethod
    def check_speak_params(self, params: Mapping[str, object]) -> None:
        """Raises ValueError naming the first parameter this provider does not take for speech or a value it would
        reject. Called once per `speak` route when the routes load."""

    @abstractmethod
    async def speak(self, model: str, params: Mapping[str, object], text: str, timeout_s: float) -> SpeechStream:
        """Start saying `text`; returns once the provider accepted the request and the first bytes have arrived,
        giving up after `timeout_s` without them. Raises ProviderFailed; never anything else."""

    async def warm(self, timeout_s: float) -> None:
        """Open what the next `speak` would otherwise open first (a connection), so it starts sooner; nothing billed.
        This default has nothing to prepare. Raises ProviderFailed; never anything else."""
        return None

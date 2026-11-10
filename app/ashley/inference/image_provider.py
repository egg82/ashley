"""What an image provider is (Strategy, beside `Provider` and the speech providers): a way to turn a prompt into a
picture. `routes.parse` rejects an `image` route whose provider is not an `ImageMaker`. Only `RoutedInference` calls it.

Failures are `provider.ProviderFailed`; a provider's safety stop is `provider.ProviderRefused`."""

from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass

from .image import Aspect
from .model import Usage
from .provider import Wired


@dataclass(frozen=True)
class Made:
    """One picture as the provider returned it: `data` non-empty, `media_type` an `image/...` type, `usage` what it
    billed by (None when it reported none)."""

    data: bytes
    media_type: str
    usage: Usage | None


class ImageMaker(Wired):
    @abstractmethod
    def check_image_params(self, params: Mapping[str, object]) -> None:
        """Raises ValueError naming the first parameter this provider does not take for images or a value it would
        reject. Called once per `image` route when the routes load."""

    @abstractmethod
    async def make(self, model: str, params: Mapping[str, object], prompt: str, aspect: Aspect,
                   timeout_s: float) -> Made:
        """Draw `prompt` (non-blank) in `aspect`, giving up after `timeout_s` with no retry of its own.
        Raises ProviderRefused when the provider's safety system declines the prompt or the picture, ProviderFailed for
        every other way it produces no picture; never anything else."""

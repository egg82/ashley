"""What an embedding provider is (Strategy, beside `Provider` and the speech providers): a way to turn text into
vectors. `routes.parse` rejects an `embed` route whose provider is not an `Embedder`. Only `RoutedInference` calls it.

Failures are `provider.ProviderFailed`, as for text; an embedder never raises `ProviderRefused`."""

from abc import abstractmethod
from collections.abc import Mapping, Sequence

from .embedding import EmbedRole
from .provider import Wired


class Embedder(Wired):
    @abstractmethod
    def check_embed_params(self, params: Mapping[str, object]) -> None:
        """Raises ValueError naming the first parameter this provider does not take for embedding or a value it would
        reject. Called once per `embed` route when the routes load."""

    @abstractmethod
    async def embed(self, model: str, params: Mapping[str, object], texts: Sequence[str], role: EmbedRole,
                    timeout_s: float) -> list[list[float]]:
        """One vector per text, in order, each of unit length, made as `role` (see `EmbedRole`); giving up after
        `timeout_s` with no retry of its own. `texts` is non-empty. Raises ProviderFailed; never anything else."""

    async def warm(self, model: str, params: Mapping[str, object], timeout_s: float) -> None:
        """Do now what the first `embed` of `model` would otherwise do first (load the model), so that call starts
        sooner; nothing billed. This default has nothing to prepare. Raises ProviderFailed; never anything else."""
        return None

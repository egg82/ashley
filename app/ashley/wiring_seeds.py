"""What each pod seeds at start from the env, best effort: Home Assistant (`ashley.home_assistant.seed`) and the model
provider keys and the local OpenAI-compatible server (`ashley.inference.key_seed`), each as the first household's
connection where it has none. Called by `ashley.wiring.warmups`."""

from collections.abc import Coroutine
from typing import Any

from . import services
from .connections.connections import Connections
from .home_assistant.seed import seed_from_env
from .inference.key_seed import seed_compatible_from_env, seed_from_env as seed_keys_from_env
from .inference.kinds import KEYED
from .settings import Settings
from .wiring_providers import env_compatible, env_keys


def seeds(settings: Settings) -> list[Coroutine[Any, Any, None]]:
    """The seeds the env asks for: one per source that has a value."""
    running: list[Coroutine[Any, Any, None]] = []
    if settings.ha_url:
        running.append(_seed(settings))
    if any(env_keys(settings).values()):
        running.append(_seed_keys(settings))
    if env_compatible(settings):
        running.append(_seed_compatible(settings))
    return running


async def _seed_keys(settings: Settings) -> None:
    await seed_keys_from_env(services.get(Connections), KEYED, env_keys(settings))


async def _seed_compatible(settings: Settings) -> None:
    await seed_compatible_from_env(services.get(Connections), env_compatible(settings))


async def _seed(settings: Settings) -> None:
    await seed_from_env(services.get(Connections), settings.ha_url, settings.ha_token)

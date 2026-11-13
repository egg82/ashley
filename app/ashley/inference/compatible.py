"""Any OpenAI-compatible model provider (OpenRouter, Groq, Together, Mistral, DeepSeek, a local Ollama or vLLM) as a
connection kind of the `inference` port: a name, a base URL and a key, many per deployment, each reached through
`OpenAICompatibleProvider` with no wrapper library (`decisions.md`, "A model provider's key is a connection").

The connection's label is the provider name routes use, so it has an identifier's shape and never takes a name a
shipped provider has (`providers.json`). Its calls are priced from the model catalogue as the catalogue provider a
person picked (`Connection.catalogue_provider`); one at a custom address has none, so its calls are unpriced."""

import httpx2
from openai import AsyncOpenAI

from ..connections.kinds import ConnectionKind, Refusal
from . import spend_catalog
from .key_check import answered
from .keyed import Built
from .provider_keys import KeyInForce
from .providers import OpenAICompatibleProvider

NAME = "openai_compatible"
MOST = 20
"""How many OpenAI-compatible providers one deployment may connect."""

LOCAL = "local"
"""The label of the connection `LOCAL_LLM_URL` seeds, which the routes have named since before it was a connection."""

LABEL_PATTERN = r"[a-z0-9][a-z0-9_-]{0,39}"


async def _check(base: str, key: str, person_id: int) -> Refusal | None:
    async with httpx2.AsyncClient() as http:
        return await answered(http, base + "/models", {"Authorization": f"Bearer {key}"})


def build(key: KeyInForce) -> Built:
    """The provider one connection turns on, named by its label and reached at its base URL. Makes no request."""
    chat = AsyncOpenAI(api_key=key.secret, base_url=key.base_url, max_retries=0)
    return Built((OpenAICompatibleProvider(key.label, chat),), {}, chat.close)


KIND = ConnectionKind(
    name=NAME, title="OpenAI-compatible provider", what="a model provider",
    blurb="Any provider that speaks OpenAI’s Chat Completions: OpenRouter, Groq, Together, Mistral, DeepSeek, or a "
          "server of your own such as Ollama or vLLM. Its name is what the routes call it.",
    connected="Connected. Routes that name it reach it from now on.",
    removed="Removed. Routes that name it are skipped.",
    holders=frozenset({"household"}), schemes=frozenset({"https", "http"}),
    address_placeholder="https://openrouter.ai/api/v1", secret_field="api_key",
    secret_label="API key (any text, for a server that takes none)", secret_noun="key", check=_check,
    ports=frozenset({"inference"}), most=MOST, deployment=True, label_pattern=LABEL_PATTERN,
    reserved_labels=frozenset(spend_catalog.load().providers), picks_catalogue_provider=True,
    refusals={"bad_url": "that is not an address a provider is reached at (https, or http on your own network)",
              "key_refused": "the provider turned that key away",
              "unreachable": "nothing answered at that address in time",
              "wrong_service": "what answered there does not list models the way OpenAI’s API does"})

"""The Wyoming speech-to-text server (faster-whisper) as a connection kind of the `inference` port: an address on the
operator's own network and no key, so the secret a connection stores is placeholder text (`NO_SECRET`). It is a
`deployment` kind held by the first household; the provider is built from its address (`build`)
by `ashley.inference.keyed_providers.KeyedProviders`, under the route name `wyoming`."""

import asyncio

from wyoming.client import AsyncClient
from wyoming.info import Describe, Info

from ..connections.kinds import ConnectionKind, Refusal
from .keyed import AddressedProvider, Built
from .wyoming_stt import WyomingTranscriber

NAME = "wyoming"
"""Both the kind's name and the route name its provider carries."""

TIMEOUT_S = 10.0


async def check(base: str, secret: str, person_id: int) -> Refusal | None:
    """Asks the server to describe itself, the read every Wyoming server answers: None when an `info` comes back;
    `unreachable` for no answer in time; `wrong_service` for a reply that is not Wyoming or a closed connection."""
    try:
        async with asyncio.timeout(TIMEOUT_S):
            async with AsyncClient.from_uri(base, connect_timeout=TIMEOUT_S, read_timeout=TIMEOUT_S) as client:
                await client.write_event(Describe().event())
                while (event := await client.read_event()) is not None:
                    if Info.is_type(event.type):
                        return None
    except (OSError, TimeoutError):
        return "unreachable"
    except ValueError:
        return "wrong_service"
    return "wrong_service"


async def _nothing() -> None:
    return None


def build(address: str) -> Built:
    """The transcriber for the server at `address`. Makes no request. Raises ValueError for an address Wyoming cannot
    reach."""
    return Built((WyomingTranscriber(NAME, address),), {}, _nothing)


KIND = ConnectionKind(
    name=NAME, title="Wyoming speech to text", what="a speech-to-text server",
    blurb="A Wyoming speech-to-text server such as faster-whisper, on your own network. Spoken turns are transcribed "
          "by it where a route names `wyoming`.",
    connected="Connected. Routes that name it reach it from now on.",
    removed="Removed. Routes that name it are skipped.",
    holders=frozenset({"household"}), schemes=frozenset({"tcp"}), address_placeholder="tcp://whisper:10300",
    secret_field="api_key", secret_label="Key (any text; the server takes none)", secret_noun="key", check=check,
    ports=frozenset({"inference"}), deployment=True,
    refusals={"bad_url": "that is not a Wyoming address; it looks like tcp://host:10300",
              "key_refused": "the server turned the connection away",
              "unreachable": "nothing answered at that address in time",
              "wrong_service": "what answered there does not speak Wyoming"})

PROVIDER = AddressedProvider(KIND, frozenset({NAME}), build)

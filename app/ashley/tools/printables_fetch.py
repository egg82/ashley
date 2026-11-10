"""How a Printables design file is opened, and the Printables service made: through `page_fetch.fetch_file`, so the request-forgery boundary holds (https,
global addresses only, checked again on every redirect, a byte cap) and every hop must be one of Printables' file hosts.
The composition root hands the result to the Printables adapter, which cannot import this."""

import httpx2

from .. import services
from ..printables import config as printables_config
from ..printables.config import PrintablesConfig
from ..printables.graphql import Fetch, GraphqlPrintables
from ..printables.printables import Printables, PrintablesFailed
from . import page_fetch


def fetcher(http: httpx2.AsyncClient, config: PrintablesConfig, resolve: page_fetch.Resolve = page_fetch.resolve) -> Fetch:
    """Opens an address within `config.download_timeout_s` and `config.max_redirects`, only on `config.file_hosts`."""
    async def fetch(url: str, max_bytes: int) -> bytes:
        limits = page_fetch.Limits(config.download_timeout_s, config.max_redirects, max_bytes)
        try:
            return await page_fetch.fetch_file(http, url, limits, config.file_hosts, resolve)
        except page_fetch.TooLarge as e:
            raise PrintablesFailed("too_large") from e
        except page_fetch.Refused as e:
            raise PrintablesFailed("unexpected") from e
        except page_fetch.NoPage as e:
            raise PrintablesFailed("unreachable") from e
    return fetch


def register(http: httpx2.AsyncClient) -> PrintablesConfig:
    """Make the Printables service over `http`, with its shipped tunables, the answer to `services.get(Printables)`;
    returns the tunables."""
    config = printables_config.load()
    services.register(Printables, GraphqlPrintables(http, config, fetcher(http, config)))
    return config

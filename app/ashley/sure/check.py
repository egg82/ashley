"""Whether Sure answers with a key: one read of its accounts, as a connection is added."""

from .. import services
from .client import Sure
from .wire import Accounts, parsed


async def accounts_seen(base: str, api_key: str) -> int:
    """How many accounts Sure at `base` shows this key. Raises SureFailed."""
    got = parsed(Accounts, await services.get(Sure).get(base, api_key, "/api/v1/accounts", {"per_page": 1}))
    return got.pagination.total_count if got.pagination is not None else len(got.accounts)

from collections.abc import Generator

import pytest
from ashley import services
from ashley.connections.kinds import ConnectionKinds
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from pkb_support import A, B, C, deployment_kind


@pytest.fixture
def provider_kinds() -> Generator[tuple[str, ...]]:
    """The three deployment kinds registered, as the app registers its model providers, beside whatever was registered."""
    services.register(ConnectionKinds, ConnectionKinds(
        services.get(ConnectionKinds).all() + tuple(deployment_kind(n) for n in (A, B, C))))
    yield (A, B, C)

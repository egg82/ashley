import pytest
from bjb_bridge_support import Pki, make_pki
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template


@pytest.fixture(scope="session")
def pki() -> Pki:
    return make_pki()

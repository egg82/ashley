import logging

import pytest
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template


@pytest.fixture
def info_logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """The events the suite reads are info lines; requested by the tests that read them, so property tests stay free of
    function-scoped fixtures."""
    caplog.set_level(logging.INFO)
    return caplog

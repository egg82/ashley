"""The etcd that `ASHLEY_TEST_ETCD_URL` names, a plain-HTTP member the lease tests may write to under unique names."""

import os

import pytest

ENV = "ASHLEY_TEST_ETCD_URL"


def etcd_url() -> str:
    """The etcd to test against. Unset fails under CI (`CI=true`), so the lease tests cannot silently stop running
    there; locally it skips, with the reason."""
    url = os.environ.get(ENV)
    if url:
        return url
    if os.environ.get("CI") == "true":
        pytest.fail(f"{ENV} is unset under CI: the lease tests must run there")
    pytest.skip(f"{ENV} is unset: no etcd to test against (CI sets it)")

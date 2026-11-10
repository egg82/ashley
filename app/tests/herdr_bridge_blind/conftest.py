from pathlib import Path

import pytest
from herdr_bridge_blind_fake import FakeHerdr
from herdr_bridge_blind_pki import Pki, make_pki
from herdr_bridge_blind_support import Bridge, build_bridge


@pytest.fixture(scope="session")
def pki() -> Pki:
    return make_pki()


@pytest.fixture
def fake() -> FakeHerdr:
    return FakeHerdr()


@pytest.fixture
def bridge(tmp_path: Path, pki: Pki, fake: FakeHerdr) -> Bridge:
    return build_bridge(tmp_path, pki, fake)

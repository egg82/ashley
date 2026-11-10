"""Media is wired only with its image and the app's address together, the sandbox and the link key behind them, and an
image pinned by digest; unwired, her frame and transcript tools are not offered (the Null Object does nothing)."""

from collections.abc import Generator
from pathlib import Path

import pytest
from ashley import services, wiring_sandbox as wiring
from ashley.runs.kube_api import KubeApi
from ashley.runs.media import Media
from ashley.runs.media_kubernetes import KubernetesMedia
from ashley.settings import Settings
import httpx2

IMAGE = "registry.example/media@sha256:" + "d" * 64
SANDBOX = {"database_url": "postgresql://x", "build_version": "t", "sandbox_token_file": "/token", "sandbox_ca_file": "/ca", "files_endpoints": "http://nas.test",
           "files_bucket": "b", "files_access_key": "k", "files_secret_key": "s", "files_link_key": "l" * 40}


@pytest.fixture
def api(tmp_path: Path) -> Generator[KubeApi]:
    yield KubeApi(httpx2.AsyncClient(base_url="https://kube.test"), str(tmp_path / "token"))
    services.unregister(Media)


def test_an_image_and_an_address_are_set_together() -> None:
    with pytest.raises(ValueError, match="MEDIA_IMAGE and MEDIA_APP_URL"):
        Settings(media_image=IMAGE, **SANDBOX)
    with pytest.raises(ValueError, match="MEDIA_IMAGE and MEDIA_APP_URL"):
        Settings(media_app_url="http://app:8080", **SANDBOX)


def test_media_needs_the_sandbox_and_the_link_key() -> None:
    with pytest.raises(ValueError, match="MEDIA_IMAGE needs"):
        Settings(database_url="postgresql://x", build_version="t", media_image=IMAGE, media_app_url="http://app:8080")
    assert Settings(media_image=IMAGE, media_app_url="http://app:8080", **SANDBOX).media_image == IMAGE


def test_an_image_pinned_by_digest_is_wired_and_a_floating_tag_is_refused(api: KubeApi) -> None:
    settings = Settings(media_image=IMAGE, media_app_url="http://app:8080", **SANDBOX)
    wiring.wire_media(settings, api)
    assert isinstance(services.get(Media), KubernetesMedia)
    loose = Settings(media_image="registry.example/media:latest", media_app_url="http://app:8080", **SANDBOX)
    with pytest.raises(ValueError, match="pinned"):
        wiring.wire_media(loose, api)


def test_unwired_nothing_is_offered() -> None:
    assert Media.null().available() is False

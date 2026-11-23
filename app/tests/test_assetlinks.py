"""`/.well-known/assetlinks.json` vouches for her Android app: answered in place as `application/json` with the package
the shell is built as and the fingerprint the setting gives, the published APK's release key when none is set, and a
malformed fingerprint refused at start."""

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ashley.settings import Settings, from_env
from ashley.web import assetlinks

FINGERPRINT = ":".join(f"{b:02X}" for b in range(32))
RELEASE_KEY = "79:1C:06:CC:3E:95:50:2F:DC:25:9A:39:0D:F0:03:10:02:09:20:85:EA:5D:30:65:08:55:9C:8A:D7:2A:01:53"
GRADLE = Path(__file__).resolve().parents[2] / "android" / "app" / "build.gradle"


def client(**fields: str) -> TestClient:
    app = FastAPI()
    app.state.settings = Settings(database_url="", build_version="t", **fields)
    app.include_router(assetlinks.router)
    return TestClient(app)


def test_set_it_names_the_package_and_fingerprint_as_json_in_place() -> None:
    got = client(android_key_sha256=FINGERPRINT).get("/.well-known/assetlinks.json", follow_redirects=False)
    assert got.status_code == 200 and got.headers["content-type"] == "application/json"
    assert got.json() == [{"relation": ["delegate_permission/common.handle_all_urls"],
                           "target": {"namespace": "android_app", "package_name": "io.github.egg82.ashley",
                                      "sha256_cert_fingerprints": [FINGERPRINT]}}]


def test_unset_it_names_the_published_apks_release_key() -> None:
    got = client().get("/.well-known/assetlinks.json")
    assert got.status_code == 200 and got.json()[0]["target"]["sha256_cert_fingerprints"] == [RELEASE_KEY]
    assert from_env({"DATABASE_URL": "x", "ANDROID_KEY_SHA256": " "}).android_key_sha256 == RELEASE_KEY


def test_the_package_is_the_one_the_shell_is_built_as() -> None:
    ids = re.findall(r"^\s*applicationId\s*=\s*'([^']+)'", GRADLE.read_text(encoding="utf-8"), re.MULTILINE)
    assert ids == [assetlinks.PACKAGE]


def test_the_env_fingerprint_is_read_in_upper_case() -> None:
    got = from_env({"DATABASE_URL": "x", "ANDROID_KEY_SHA256": f" {FINGERPRINT.lower()} "})
    assert got.android_key_sha256 == FINGERPRINT


@pytest.mark.parametrize("bad", ["", FINGERPRINT[:-3], FINGERPRINT + ":00", FINGERPRINT.replace(":", ""),
                                 "ZZ" + FINGERPRINT[2:], FINGERPRINT.lower()])
def test_a_malformed_fingerprint_is_refused(bad: str) -> None:
    with pytest.raises(ValueError, match="ANDROID_KEY_SHA256"):
        Settings(database_url="", build_version="t", android_key_sha256=bad)


def test_the_app_serves_it_ahead_of_the_client() -> None:
    from ashley.main import create_app

    app = create_app(Settings(database_url="", build_version="t", android_key_sha256=FINGERPRINT))
    got = TestClient(app).get("/.well-known/assetlinks.json", follow_redirects=False)
    assert got.status_code == 200 and got.json()[0]["target"]["sha256_cert_fingerprints"] == [FINGERPRINT]

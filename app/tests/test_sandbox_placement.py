"""Where the sandbox's pods go is a deployment setting: `SANDBOX_NAMESPACE` and `SANDBOX_RUNTIME_CLASS`, defaulting to
the namespace and gVisor class the cluster repo ships. A pod each of code runs, looks and media is made in the namespace
and under the class the settings name, and a value the Kubernetes API would not take is refused naming its variable."""

import asyncio
import base64
import json
from collections.abc import Generator
from pathlib import Path

import pytest
from ashley import services, wiring_sandbox
from ashley.looks.looker import Looker, Target
from ashley.runs.config import FILE
from ashley.runs.model import Job
from ashley.runs.kubernetes import KubernetesSandbox
from ashley.runs.media import Media, Source
from ashley.settings import Settings, from_env
from sandbox_support import CONFIG, FakeKube, Script, envelope_line

BASE = {"database_url": "postgresql://x", "build_version": "t", "sandbox_token_file": "/token", "sandbox_ca_file": "/ca",
        "files_endpoints": "http://nas.test", "files_bucket": "b", "files_access_key": "k", "files_secret_key": "s",
        "files_link_key": "l" * 40, "look_image": "registry.example/look@sha256:" + "e" * 64,
        "look_app_url": "http://app:8080", "media_image": "registry.example/media@sha256:" + "d" * 64,
        "media_app_url": "http://app:8080"}
OTHER = {"sandbox_namespace": "elsewhere", "sandbox_runtime_class": "kata"}
JPEG = b"\xff\xd8\xff\xe0" + b"p" * 30


@pytest.fixture(autouse=True)
def unwire() -> Generator[None]:
    yield
    services.unregister(Looker)
    services.unregister(Media)


def test_the_defaults_are_the_namespace_and_class_the_cluster_repo_ships() -> None:
    settings = from_env({"DATABASE_URL": "postgresql://x"})
    assert (settings.sandbox_namespace, settings.sandbox_runtime_class) == ("ashley-sandbox", "gvisor")


def test_the_environment_names_the_namespace_and_the_class() -> None:
    settings = from_env({"DATABASE_URL": "postgresql://x", "SANDBOX_NAMESPACE": " elsewhere ", "SANDBOX_RUNTIME_CLASS": "kata"})
    assert (settings.sandbox_namespace, settings.sandbox_runtime_class) == ("elsewhere", "kata")


@pytest.mark.parametrize("env", ["SANDBOX_NAMESPACE", "SANDBOX_RUNTIME_CLASS"])
@pytest.mark.parametrize("value", ["", "Has Caps", "a/b", "../x", "-x"])
def test_a_name_the_api_would_not_take_is_refused_naming_its_variable(env: str, value: str) -> None:
    with pytest.raises(ValueError, match=env):
        from_env({"DATABASE_URL": "postgresql://x", env: value})


def test_a_runtime_class_may_have_dots_and_a_namespace_may_not() -> None:
    assert from_env({"DATABASE_URL": "postgresql://x", "SANDBOX_RUNTIME_CLASS": "runsc.v2"}).sandbox_runtime_class == "runsc.v2"
    with pytest.raises(ValueError, match="SANDBOX_NAMESPACE"):
        from_env({"DATABASE_URL": "postgresql://x", "SANDBOX_NAMESPACE": "a.b"})


def test_the_shipped_runs_data_no_longer_holds_them() -> None:
    assert {"namespace", "runtime_class"}.isdisjoint(json.loads(FILE.read_text()))


def test_a_code_run_pod_is_made_in_the_set_namespace_under_the_set_class(tmp_path: Path) -> None:
    fake = FakeKube(tmp_path / "token", Script(log=envelope_line()))
    asyncio.run(KubernetesSandbox(fake.api(), CONFIG, "elsewhere", "kata").run(_job()))
    assert fake.created[0]["metadata"]["namespace"] == "elsewhere" and fake.created[0]["spec"]["runtimeClassName"] == "kata"


def test_a_look_pod_is_made_in_the_set_namespace_under_the_set_class(tmp_path: Path) -> None:
    from ashley.looks.kubernetes import MARK

    fake = FakeKube(tmp_path / "token", Script(log=MARK + base64.b64encode(JPEG).decode()))
    wiring_sandbox.wire_looker(Settings(**BASE, **OTHER), fake.api(), [])
    asyncio.run(services.get(Looker).look("look-a1", Target(household_id=3, person_id=5, bench_id=9, piece_id=None)))
    assert fake.created[0]["metadata"]["namespace"] == "elsewhere" and fake.created[0]["spec"]["runtimeClassName"] == "kata"


def test_a_media_pod_is_made_in_the_set_namespace_under_the_set_class(tmp_path: Path) -> None:
    from ashley.runs.media_kubernetes import MARK

    line = MARK + json.dumps({"kind": "frames", "duration": 61.5, "count": 2, "jpeg": base64.b64encode(JPEG).decode()})
    fake = FakeKube(tmp_path / "token", Script(log=line))
    wiring_sandbox.wire_media(Settings(**BASE, **OTHER), fake.api())
    source = Source(household_id=3, sha256="a" * 64, size=1234, media_type="video/mp4")
    asyncio.run(services.get(Media).frames("media-a1", source, (1.0, 2.0)))
    assert fake.created[0]["metadata"]["namespace"] == "elsewhere" and fake.created[0]["spec"]["runtimeClassName"] == "kata"


def _job() -> Job:
    return Job("run-1", "python", "print(1)")

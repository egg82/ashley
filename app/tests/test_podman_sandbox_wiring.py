"""`SANDBOX_PODMAN=trusted` is the opt-in that wires `PodmanSandbox`; it excludes the Kubernetes sandbox settings."""

import logging
import ssl
from collections.abc import Callable, Coroutine, Generator
from typing import Any

import pytest
from ashley import services, wiring_sandbox as wiring
from ashley.runs.kubernetes import KubernetesSandbox
from ashley.runs.podman import PodmanSandbox
from ashley.runs.sandbox import Sandbox
from speech_support import no_whisper
from ashley.settings import Settings, from_env

BASE = {"database_url": "postgresql://x", "build_version": "t"}
KUBE = {"sandbox_token_file": "/token", "sandbox_ca_file": "/ca"}


@pytest.fixture(autouse=True)
def clean(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    plain = ssl.create_default_context

    def without_file(cafile: str) -> ssl.SSLContext:
        return plain()

    monkeypatch.setattr(ssl, "create_default_context", without_file)
    services.unregister(Sandbox)
    yield
    services.unregister(Sandbox)


def test_the_environment_variable_is_read_and_trimmed() -> None:
    assert from_env({"DATABASE_URL": "postgresql://x", "SANDBOX_PODMAN": " trusted\n"}).sandbox_podman == "trusted"


def test_unset_it_is_empty() -> None:
    assert from_env({"DATABASE_URL": "postgresql://x"}).sandbox_podman == ""


def test_any_other_value_is_refused() -> None:
    with pytest.raises(ValueError, match="SANDBOX_PODMAN must be"):
        Settings(**BASE, sandbox_podman="yes")


@pytest.mark.parametrize("kube", [KUBE, {"sandbox_ca_file": "/ca"}])
def test_both_sandboxes_are_refused_naming_both_variables(kube: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="SANDBOX_PODMAN and SANDBOX_TOKEN_FILE"):
        Settings(**BASE, sandbox_podman="trusted", **kube)


def test_the_opt_in_alone_wires_the_podman_sandbox(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="ashley.runs"):
        wiring.wire_podman_sandbox()
    assert isinstance(services.get(Sandbox), PodmanSandbox)
    assert [r.levelno for r in caplog.records if "runs.sandbox_podman" in r.getMessage()] == [logging.WARNING]


def test_the_kubernetes_settings_without_it_still_wire_the_kubernetes_sandbox() -> None:
    closers: list[Callable[[], Coroutine[Any, Any, None]]] = []
    wiring.wire_sandbox(Settings(**BASE, **KUBE), closers, no_whisper)
    assert isinstance(services.get(Sandbox), KubernetesSandbox)


def test_neither_leaves_no_sandbox() -> None:
    assert services.get(Sandbox).languages() == ()

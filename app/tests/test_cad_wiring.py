"""The CAD image is `CAD_IMAGE`: it needs the sandbox settings, must be pinned by digest, and makes the one Sandbox run
build123d too; unset, the Sandbox runs Python only."""

import ssl
from collections.abc import Callable, Coroutine, Generator
from typing import Any

import pytest
from ashley import services, wiring_sandbox as wiring
from ashley.runs.sandbox import Sandbox
from speech_support import no_whisper
from ashley.settings import Settings, from_env

CAD = "registry.example/ashley-cad@sha256:" + "c" * 64
SANDBOX = {"sandbox_token_file": "/token", "sandbox_ca_file": "/ca"}


@pytest.fixture(autouse=True)
def no_ca(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    plain = ssl.create_default_context

    def without_file(cafile: str) -> ssl.SSLContext:
        return plain()

    monkeypatch.setattr(ssl, "create_default_context", without_file)
    yield
    services.unregister(Sandbox)


def wired(settings: Settings) -> Sandbox:
    closers: list[Callable[[], Coroutine[Any, Any, None]]] = []
    wiring.wire_sandbox(settings, closers, no_whisper)
    return services.get(Sandbox)


def test_the_environment_variable_is_read_and_trimmed() -> None:
    env = {"DATABASE_URL": "postgresql://x", "CAD_IMAGE": f" {CAD}\n", **{k.upper(): v for k, v in SANDBOX.items()}}
    assert from_env(env).cad_image == CAD


def test_the_image_needs_the_sandbox_settings() -> None:
    with pytest.raises(ValueError, match="CAD_IMAGE needs"):
        Settings(database_url="postgresql://x", build_version="t", cad_image=CAD)


def test_an_image_pinned_by_digest_makes_the_sandbox_run_build123d() -> None:
    sandbox = wired(Settings(database_url="postgresql://x", build_version="t", cad_image=CAD, **SANDBOX))
    assert sandbox.languages() == ("python", "build123d")


def test_without_it_the_sandbox_runs_python_only() -> None:
    sandbox = wired(Settings(database_url="postgresql://x", build_version="t", **SANDBOX))
    assert sandbox.languages() == ("python",)


def test_a_floating_tag_is_refused() -> None:
    with pytest.raises(ValueError, match="pinned"):
        wired(Settings(database_url="postgresql://x", build_version="t", cad_image="registry.example/cad:latest",
                       **SANDBOX))

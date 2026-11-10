"""The Sandbox service (`ashley.services`), the Strategy a code run goes through: where and how one script runs, with
no network, no credentials and no state kept after it. `kubernetes.KubernetesSandbox` runs each job in its own gVisor
pod; the Null Object offers no language, so `run_code` is not offered at all."""

from abc import abstractmethod

from ..services import Service
from .model import Job, Language, Output


class SandboxUnavailable(Exception):
    """The job could not be run at all (the cluster unreachable, the pod refused or never started). Nothing it
    printed is known."""


class Sandbox(Service):
    @classmethod
    def null(cls) -> "Sandbox":
        return NullSandbox()

    @abstractmethod
    def languages(self) -> tuple[Language, ...]:
        """The languages it runs; empty when it runs nothing."""

    @abstractmethod
    async def run(self, job: Job) -> Output:
        """Run `job` once and return what came out. Never raises for what the script did (an error, a timeout, too
        much memory are each an `Output`). Raises SandboxUnavailable when it could not run it. Leaves nothing behind:
        whatever ran the job is gone when this returns or raises."""


class NullSandbox(Sandbox):
    def languages(self) -> tuple[Language, ...]:
        return ()

    async def run(self, job: Job) -> Output:
        raise SandboxUnavailable("Sandbox is not wired")

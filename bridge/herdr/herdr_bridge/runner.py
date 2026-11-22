"""How the bridge runs the `herdr` CLI: a Runner takes the arguments after `herdr` and returns what it printed."""

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Outcome:
    code: int
    out: str
    err: str


class HerdrMissing(Exception):
    """The `herdr` binary could not be started."""


class HerdrTimeout(Exception):
    """`herdr` was started and did not finish in time; whether it acted is unknown."""


class Runner(Protocol):
    def run(self, args: Sequence[str], timeout_s: float) -> Outcome: ...


@dataclass(frozen=True)
class Captured:
    code: int
    data: bytes
    err: str


class Capturer(Protocol):
    def capture(self, args: Sequence[str], timeout_s: float) -> Captured:
        """Run with `args` and return what the program wrote to stdout, as bytes. Raises HerdrMissing, HerdrTimeout."""
        ...


class SubprocessRunner:
    def __init__(self, binary: str) -> None:
        self.binary = binary

    def run(self, args: Sequence[str], timeout_s: float) -> Outcome:
        try:
            done = subprocess.run(
                [self.binary, *args], capture_output=True, text=True, timeout=timeout_s, stdin=subprocess.DEVNULL
            )
        except subprocess.TimeoutExpired as e:
            raise HerdrTimeout(str(args[:2])) from e
        except OSError as e:
            raise HerdrMissing(self.binary) from e
        return Outcome(done.returncode, done.stdout, done.stderr)


class SubprocessCapturer:
    def __init__(self, binary: str) -> None:
        self.binary = binary

    def capture(self, args: Sequence[str], timeout_s: float) -> Captured:
        try:
            done = subprocess.run([self.binary, *args], capture_output=True, timeout=timeout_s, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as e:
            raise HerdrTimeout(self.binary) from e
        except OSError as e:
            raise HerdrMissing(self.binary) from e
        return Captured(done.returncode, done.stdout, done.stderr.decode(errors="replace"))

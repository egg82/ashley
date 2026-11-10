"""Bridge as a child process of the keeper: `bridge --grpc`, its own logs discarded (they name users), and a gRPC link to it
once it has written its server config."""

import subprocess
import time
from pathlib import Path

from keeper_files import CONFIG
from keeper_grpc import GrpcBridge
from keeper_link import BridgeLink

BINARY = "/usr/lib/protonmail/bridge/bridge"
UP_S = 90.0


class BridgeProcess:
    def __init__(self, popen: "subprocess.Popen[bytes]", link: BridgeLink) -> None:
        self._popen = popen
        self.link = link

    def alive(self) -> bool:
        return self._popen.poll() is None

    def kill(self) -> None:
        self.link.close()
        self._popen.kill()
        self._popen.wait(timeout=10)


def start(home: Path, binary: str = BINARY) -> BridgeProcess:
    """Start Bridge with HOME `home` and link to it. Raises TimeoutError when it is not up in `UP_S`, RuntimeError when it
    exits first."""
    popen = subprocess.Popen([binary, "--grpc", "--log-level", "warn"], env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    config = home / CONFIG
    deadline = time.monotonic() + UP_S
    while not (config / "grpcServerConfig.json").exists():
        if popen.poll() is not None:
            raise RuntimeError("bridge exited before it was up")
        if time.monotonic() > deadline:
            popen.kill()
            raise TimeoutError("bridge was not up in time")
        time.sleep(0.5)
    time.sleep(1.0)
    return BridgeProcess(popen, GrpcBridge(config))

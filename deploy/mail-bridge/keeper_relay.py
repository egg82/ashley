"""Bridge listens for IMAP and SMTP on its loopback only; a relay in the keeper listens on the pod's own port and copies
bytes both ways to it. Each accepted connection is a turn of the keeper first, so a changed vault is written back before
a client is let through."""

import socket
import threading
from collections.abc import Callable

CHUNK = 65536


class Relay:
    def __init__(self, listen_port: int, target_port: int, before: Callable[[], None], host: str = "0.0.0.0") -> None:
        self._target = target_port
        self._before = before
        self._server = socket.create_server((host, listen_port))
        self.port: int = self._server.getsockname()[1]

    def serve(self) -> None:
        """Accept until closed; one thread per connection."""
        while True:
            try:
                client, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def close(self) -> None:
        self._server.close()

    def _handle(self, client: socket.socket) -> None:
        try:
            self._before()
            upstream = socket.create_connection(("127.0.0.1", self._target), timeout=10)
        except Exception:
            client.close()
            return
        upstream.settimeout(None)
        threading.Thread(target=_pump, args=(upstream, client), daemon=True).start()
        _pump(client, upstream)


def _pump(source: socket.socket, sink: socket.socket) -> None:
    try:
        while data := source.recv(CHUNK):
            sink.sendall(data)
    except OSError:
        pass
    finally:
        for end in (source, sink):
            try:
                end.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            end.close()

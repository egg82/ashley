"""Who may call: the token the bridge printed at install, and the one person it serves."""

import hashlib
import hmac
import os
import re
import threading
from pathlib import Path

from .errors import BridgeError

TOKEN_FILE = "token.sha256"
PERSON_FILE = "person"
PERSON_ID = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Auth:
    """Only the token's sha256 is kept. The first call with a valid token records its person id in the state
    directory and every other person is refused from then on, until the bridge is set up again."""

    def __init__(self, state_dir: Path) -> None:
        self.person_path = state_dir / PERSON_FILE
        self.digest = (state_dir / TOKEN_FILE).read_text().strip()
        self.lock = threading.Lock()

    def check(self, authorization: str | None, person: str | None) -> str:
        """The person id this call is for; raises bad_token or wrong_person."""
        scheme, _, token = (authorization or "").partition(" ")
        if scheme != "Bearer" or not hmac.compare_digest(token_digest(token), self.digest):
            raise BridgeError("bad_token")
        if person is None or not PERSON_ID.fullmatch(person):
            raise BridgeError("wrong_person")
        with self.lock:
            known = self.person_path.read_text().strip() if self.person_path.exists() else None
            if known is None:
                self.record(person)
            elif known != person:
                raise BridgeError("wrong_person")
        return person

    def record(self, person: str) -> None:
        tmp = self.person_path.with_name(PERSON_FILE + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(person + "\n")
        os.replace(tmp, self.person_path)

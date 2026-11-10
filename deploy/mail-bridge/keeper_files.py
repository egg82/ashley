"""The files Bridge keeps and the keeper moves: the vault (`vault.enc`) and the keychain that opens it, which is `pass`'s
store, its GPG home and Bridge's two keychain marker files. A first start makes a GPG key with no passphrase and a `pass`
store on it, which Bridge then fills with the key to its vault; every later pod installs what was written back."""

import hashlib
import io
import os
import stat
import tarfile
from collections.abc import Callable, Sequence
from pathlib import Path

CONFIG = Path(".config/protonmail/bridge-v3")
VAULT = CONFIG / "vault.enc"
KEYCHAIN = (Path(".password-store"), Path(".gnupg"), CONFIG / "keychain.json", CONFIG / "keychain_state.json")
Runner = Callable[[Sequence[str]], None]
"""Runs a command with HOME set, raising when it fails."""


def vault_bytes(home: Path) -> bytes | None:
    """The vault as it is on disk, or None when there is none or it changed while read (Bridge was mid-write)."""
    path = home / VAULT
    try:
        first = path.read_bytes()
        again = path.read_bytes()
    except FileNotFoundError:
        return None
    return first if first == again else None


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def pack_keychain(home: Path) -> bytes:
    """The keychain as a tar of regular files and directories under `home` (sockets are not kept)."""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as tar:
        for top in KEYCHAIN:
            for path in _walk(home / top):
                if path.is_symlink():
                    continue
                mode = path.lstat().st_mode
                if stat.S_ISREG(mode) or stat.S_ISDIR(mode):
                    tar.add(path, arcname=str(path.relative_to(home)), recursive=False)
    return out.getvalue()


def _walk(root: Path) -> list[Path]:
    if not root.exists():
        return []
    found = [root]
    for base, dirs, files in os.walk(root):
        found += [Path(base) / name for name in (*dirs, *files)]
    return found


def install(home: Path, vault: bytes | None, keychain: bytes | None, run: Runner) -> None:
    """Put what the record holds into `home`; with no vault yet, make the first keychain."""
    config = home / CONFIG
    config.mkdir(parents=True, exist_ok=True)
    if vault is None or keychain is None:
        _first_keychain(home, run)
        return
    _unpack(home, keychain)
    (home / VAULT).write_bytes(vault)
    (home / ".gnupg").chmod(0o700)


def _unpack(home: Path, keychain: bytes) -> None:
    allowed = tuple(str(p) for p in KEYCHAIN)
    with tarfile.open(fileobj=io.BytesIO(keychain), mode="r") as tar:
        for member in tar.getmembers():
            name = Path(member.name)
            safe = not name.is_absolute() and ".." not in name.parts and str(name).startswith(allowed)
            if not safe or not (member.isreg() or member.isdir()):
                raise ValueError("the keychain holds something that is not its own")
            target = home / name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = tar.extractfile(member)
            assert source is not None
            target.write_bytes(source.read())
            target.chmod(member.mode & 0o700 | 0o600)


def _first_keychain(home: Path, run: Runner) -> None:
    (home / ".gnupg").mkdir(mode=0o700, exist_ok=True)
    run(["gpg", "--batch", "--passphrase", "", "--quick-gen-key", "bridge-keeper", "default", "default", "never"])
    run(["pass", "init", "bridge-keeper"])

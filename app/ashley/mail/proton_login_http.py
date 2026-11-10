"""ProtonLogin over HTTP to the keeper (`deploy/mail-bridge/keeper.py`), reached at the Bridge Service address of each
site in turn, with the token and control-port certificate of the current epoch read from the record both sites share
(`ProtonBridge.keeper_access`), since the pod's Secret is in one cluster only. The keeper's routes are `POST /login`,
`/login/verified`, `/login/two-factor`, `/login/mailbox-password` and `/forget`, each answering JSON with a `step` (`two_factor`,
`mailbox_password`, `human_verification`, `connected`, `refused`) as `Ask`, `Verify`, `Done` and `Refused` carry. What is typed is in the request body
only, over TLS under that certificate, which is the only one the app accepts for the pod (`proton_tls`)."""

import logging
import ssl
from typing import Any, get_args, get_type_hints
from urllib.parse import urlsplit

import httpx2

from .. import logs
from ..runs.loose import as_list, as_object
from . import proton_tls
from .proton_bridge import BridgeUnavailable, ProtonBridge
from .proton_login import Ask, Done, LoginStep, ProtonLogin, Refused, Verify

log = logging.getLogger("ashley.mail")
CONNECT_TIMEOUT_S = 3.0


class KeeperLogin(ProtonLogin):
    def __init__(self, keeper_urls: tuple[str, ...], bridge: ProtonBridge, timeout_s: float) -> None:
        """`keeper_urls` are the Bridge Service addresses (`https://host:port`), this site's first. A step goes to the
        first that accepts a connection; only a failure to connect moves on to the next, never an answer or a failed
        certificate check."""
        self._urls = keeper_urls
        self._bridge = bridge
        self._timeout = timeout_s

    async def begin(self, username: str, password: str) -> LoginStep:
        return _step(await self._post("/login", {"username": username, "password": password}))

    async def verified(self, password: str) -> LoginStep:
        return _step(await self._post("/login/verified", {"password": password}))

    async def second_factor(self, code: str) -> LoginStep:
        return _step(await self._post("/login/two-factor", {"code": code}))

    async def mailbox_password(self, password: str) -> LoginStep:
        return _step(await self._post("/login/mailbox-password", {"password": password}))

    async def forget(self, user_id: str) -> None:
        await self._post("/forget", {"user_id": user_id})

    async def _post(self, path: str, body: dict[str, str]) -> dict[str, Any]:
        access = await self._bridge.keeper_access((await self._bridge.holder()).epoch)
        if access is None:
            raise BridgeUnavailable("Bridge is not running")
        timeout = httpx2.Timeout(self._timeout, connect=CONNECT_TIMEOUT_S)
        async with httpx2.AsyncClient(verify=proton_tls.trusting(access.certificate)) as http:
            for url in self._urls:
                try:
                    got = await http.post(url + path, json=body, timeout=timeout,
                                          headers={"Authorization": f"Bearer {access.token}"})
                except (httpx2.ConnectError, httpx2.ConnectTimeout) as e:
                    if _tls_failure(e):
                        raise BridgeUnavailable(type(e).__name__) from e
                    logs.warning(log, "proton_bridge.keeper_unreachable", path=path, error=type(e).__name__)
                    continue
                except httpx2.HTTPError as e:
                    raise BridgeUnavailable(type(e).__name__) from e
                return _answer(path, got)
        raise BridgeUnavailable("no keeper address accepted a connection")


def _tls_failure(error: BaseException) -> bool:
    seen: BaseException | None = error
    while seen is not None:
        if isinstance(seen, ssl.SSLError):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def _answer(path: str, got: httpx2.Response) -> dict[str, Any]:
    answer = as_object(got.json()) if got.status_code == 200 else None
    if answer is None:
        logs.warning(log, "proton_bridge.login_failed", path=path, status=got.status_code)
        raise BridgeUnavailable(f"the keeper answered {got.status_code}")
    return answer


def _step(answer: dict[str, Any]) -> LoginStep:
    step = answer.get("step")
    if step in ("two_factor", "mailbox_password"):
        return Ask(step)
    if step == "human_verification":
        url = answer.get("url")
        if isinstance(url, str) and _proton_page(url):
            return Verify(url)
        raise BridgeUnavailable("the keeper's answer is malformed")
    if step == "connected":
        addresses = as_list(answer.get("addresses"))
        fields = (answer.get("user_id"), answer.get("bridge_password"), answer.get("epoch"), answer.get("synced"))
        user, password, epoch, synced = fields
        if (isinstance(user, str) and isinstance(password, str) and type(epoch) is int and isinstance(synced, bool)
                and addresses is not None and all(isinstance(a, str) for a in addresses)):
            return Done(user, tuple(str(a) for a in addresses), password, epoch, synced)
        raise BridgeUnavailable("the keeper's answer is malformed")
    if step != "refused":
        raise BridgeUnavailable("the keeper's answer is malformed")
    reason = answer.get("reason")
    for known in get_args(get_type_hints(Refused)["reason"]):
        if reason == known:
            return Refused(known)
    return Refused("other")


def _proton_page(url: str) -> bool:
    """Whether `url` is an https page on proton.me or a subdomain of it, safe to hand to a browser."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    return parts.scheme == "https" and (host == "proton.me" or host.endswith(".proton.me")) and not parts.username

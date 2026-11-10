"""`Patroni` read from its keys in the referee's etcd and driven through its REST API."""

import json
import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx2

from .. import logs
from .etcd_gateway import EtcdGateway, EtcdTls, EtcdUnavailable
from .patroni import ClusterView, Member, Patroni, PatroniUnavailable, Promotion

log = logging.getLogger("ashley.referee.patroni")


class EtcdPatroni(Patroni):
    """`url`/`tls` reach this site's etcd member; `prefix` is Patroni's `<namespace><scope>/`. `auth` is the REST API's
    user and password, which `switchover` sends to the leader's `api_url` host. `rest_transport` replaces the REST
    client's transport (etcd's is never replaced)."""

    def __init__(self, url: str, tls: EtcdTls | None = None, prefix: str = "/service/postgres/",
                 auth: tuple[str, str] = ("patroni", ""), timeout: float = 10.0,
                 rest_transport: httpx2.AsyncBaseTransport | None = None) -> None:
        self._url = url
        self._tls = tls
        self._prefix = prefix
        self._auth = auth
        self._timeout = timeout
        self._rest_transport = rest_transport

    async def view(self) -> ClusterView:
        try:
            async with EtcdGateway(self._url, self._timeout, self._tls) as etcd:
                keys = await etcd.prefix(self._prefix)
        except EtcdUnavailable as e:
            raise PatroniUnavailable(f"etcd:{e}") from e
        try:
            return _parse(keys, self._prefix)
        except (ValueError, KeyError, TypeError, AttributeError, IndexError) as e:
            raise PatroniUnavailable(type(e).__name__) from e

    async def switchover(self, leader: str, candidate: str) -> bool:
        try:
            view = await self.view()
        except PatroniUnavailable as e:
            logs.warning(log, "patroni.switchover_unread", error=str(e))
            return False
        member = view.members.get(leader)
        if member is None:
            logs.warning(log, "patroni.switchover_no_member", leader=leader)
            return False
        parts = urlsplit(member.api_url)
        async with httpx2.AsyncClient(base_url=f"{parts.scheme}://{parts.netloc}", timeout=self._timeout * 6,
                                      auth=self._auth, transport=self._rest_transport) as client:
            try:
                resp = await client.post("/switchover", json={"leader": leader, "candidate": candidate})
            except httpx2.HTTPError as e:
                logs.warning(log, "patroni.switchover_unreachable", leader=leader, error=type(e).__name__)
                return False
        if resp.status_code != 200:
            logs.warning(log, "patroni.switchover_refused", leader=leader, candidate=candidate,
                         status=resp.status_code)
            return False
        logs.info(log, "patroni.switched_over", leader=leader, candidate=candidate)
        return True


def _parse(keys: dict[str, str], prefix: str) -> ClusterView:
    members: dict[str, Member] = {}
    for key, value in keys.items():
        if key.startswith(prefix + "members/"):
            name = key.removeprefix(prefix + "members/")
            members[name] = _member(name, json.loads(value))
    history_raw = keys.get(prefix + "history")
    history = tuple(_promotion(e) for e in json.loads(history_raw)) if history_raw else ()
    return ClusterView(leader=keys.get(prefix + "leader") or None, members=members, history=history)


def _member(name: str, data: dict[str, Any]) -> Member:
    role = str(data.get("role", ""))
    position = data.get("xlog_location") if role in ("primary", "master") else data.get("replay_lsn")
    timeline = data.get("timeline")
    return Member(name=name, role="primary" if role == "master" else role, state=str(data.get("state", "")),
                  timeline=int(timeline) if timeline is not None else None,
                  wal=int(position) if position is not None else None,
                  replication_state=data.get("replication_state"), api_url=str(data.get("api_url", "")))


def _promotion(entry: list[Any]) -> Promotion:
    """`[timeline, lsn, reason, timestamp, new_leader]`; older Patroni wrote only the first three or four."""
    at = datetime.fromisoformat(entry[3]) if len(entry) > 3 else datetime.min
    return Promotion(timeline=int(entry[0]), at=at if at.tzinfo else at.replace(tzinfo=UTC),
                     new_leader=entry[4] if len(entry) > 4 else None)

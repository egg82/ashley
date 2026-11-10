"""Patroni contract: `EtcdPatroni` reads Patroni's real etcd layout and drives its REST API; `ClusterView.lag`."""

import asyncio
import base64
import json
import uuid
from datetime import UTC, datetime

import httpx2
import pytest
from ashley.referee.patroni import ClusterView, Member, Patroni, PatroniUnavailable, Promotion
from ashley.referee.patroni_etcd import EtcdPatroni
from etcd import etcd_url
from hypothesis import given
from hypothesis import strategies as st
from lease_support import put

WILLOW = ('{"conn_url":"postgres://10.99.0.222:5432/postgres","api_url":"http://10.99.0.222:8008/patroni",'
          '"state":"running","role":"primary","version":"4.1.0","xlog_location":318771432,"timeline":8}')
BIRCH = ('{"conn_url":"postgres://10.99.0.223:5432/postgres","api_url":"http://10.99.0.223:8008/patroni",'
         '"state":"running","role":"replica","version":"4.1.0","xlog_location":318771432,"replay_lsn":318771432,'
         '"receive_lsn":318771432,"replication_state":"streaming","timeline":8}')
HISTORY = ('[[6,150995104,"no recovery target specified","2026-03-14T12:00:00.500000+00:00","birch"],'
           '[7,218103968,"no recovery target specified","2026-03-14T12:01:00.250000+00:00","willow"]]')


def new_prefix() -> str:
    return f"/ashley-test/patroni-{uuid.uuid4().hex[:12]}/postgres/"


def seed(prefix: str, leader: str | None = "willow", willow: str = WILLOW, birch: str = BIRCH, history: str | None = HISTORY) -> None:
    """Patroni's keys as captured live, plus the keys the referee must ignore."""
    if leader is not None:
        put(prefix + "leader", leader)
    put(prefix + "members/willow", willow)
    put(prefix + "members/birch", birch)
    if history is not None:
        put(prefix + "history", history)
    put(prefix + "config", '{"ttl":30,"loop_wait":10,"retry_timeout":10,"postgresql":{"use_pg_rewind":true}}')
    put(prefix + "status", '{"optime":318771432,"slots":{"birch":318771432}}')
    put(prefix + "failover", '{"leader":"willow","candidate":"birch"}')
    put(prefix + "initialize", "7564123456789012345")


def view_of(patroni: Patroni) -> ClusterView:
    return asyncio.run(patroni.view())


def test_view_reads_the_live_layout() -> None:
    prefix = new_prefix()
    seed(prefix)
    view = view_of(EtcdPatroni(etcd_url(), prefix=prefix))
    assert view.leader == "willow"
    assert set(view.members) == {"willow", "birch"}
    assert view.members["willow"] == Member(
        name="willow", role="primary", state="running", timeline=8, wal=318771432, replication_state=None,
        api_url="http://10.99.0.222:8008/patroni")
    assert view.members["birch"] == Member(
        name="birch", role="replica", state="running", timeline=8, wal=318771432, replication_state="streaming",
        api_url="http://10.99.0.223:8008/patroni")
    assert view.history == (
        Promotion(6, datetime(2026, 3, 14, 12, 0, 0, 500000, tzinfo=UTC), "birch"),
        Promotion(7, datetime(2026, 3, 14, 12, 1, 0, 250000, tzinfo=UTC), "willow"),
    )


def test_a_replica_position_is_its_replay_lsn_not_its_xlog_location() -> None:
    prefix = new_prefix()
    birch = json.dumps({**json.loads(BIRCH), "xlog_location": 5, "replay_lsn": 100, "receive_lsn": 7})
    seed(prefix, birch=birch)
    assert view_of(EtcdPatroni(etcd_url(), prefix=prefix)).members["birch"].wal == 100


def test_a_primary_position_is_its_xlog_location() -> None:
    prefix = new_prefix()
    willow = json.dumps({**json.loads(WILLOW), "xlog_location": 4242})
    seed(prefix, willow=willow)
    assert view_of(EtcdPatroni(etcd_url(), prefix=prefix)).members["willow"].wal == 4242


def test_unreported_fields_are_none() -> None:
    prefix = new_prefix()
    bare = json.dumps({"api_url": "http://10.0.0.9:8008/patroni", "state": "starting", "role": "replica"})
    seed(prefix, birch=bare)
    birch = view_of(EtcdPatroni(etcd_url(), prefix=prefix)).members["birch"]
    assert (birch.wal, birch.timeline, birch.replication_state) == (None, None, None)
    assert (birch.state, birch.role) == ("starting", "replica")


def test_no_leader_key_means_no_leader() -> None:
    prefix = new_prefix()
    seed(prefix, leader=None)
    view = view_of(EtcdPatroni(etcd_url(), prefix=prefix))
    assert view.leader is None
    assert set(view.members) == {"willow", "birch"}


def test_no_history_key_means_no_history() -> None:
    prefix = new_prefix()
    seed(prefix, history=None)
    assert view_of(EtcdPatroni(etcd_url(), prefix=prefix)).history == ()


def test_older_history_entries_have_no_new_leader() -> None:
    prefix = new_prefix()
    seed(prefix, history='[[5,100,"no recovery target specified","2026-03-14T11:00:00+00:00"]]')
    history = view_of(EtcdPatroni(etcd_url(), prefix=prefix)).history
    assert history == (Promotion(5, datetime(2026, 3, 14, 11, 0, tzinfo=UTC), None),)


def test_an_empty_cluster_reads_as_empty() -> None:
    view = view_of(EtcdPatroni(etcd_url(), prefix=new_prefix()))
    assert (view.leader, view.members, view.history) == (None, {}, ())


def test_only_keys_under_the_prefix_are_read() -> None:
    prefix, other = new_prefix(), new_prefix()
    seed(prefix)
    put(other + "leader", "zzz")
    put(other + "members/zzz", WILLOW)
    view = view_of(EtcdPatroni(etcd_url(), prefix=prefix))
    assert view.leader == "willow"
    assert set(view.members) == {"willow", "birch"}


@pytest.mark.parametrize("key,value", [
    ("members/birch", "not json"),
    ("members/birch", "[1, 2]"),
    ("history", "not json"),
    ("history", '{"a": 1}'),
])
def test_a_reply_that_is_not_understood_is_unavailable(key: str, value: str) -> None:
    prefix = new_prefix()
    seed(prefix)
    put(prefix + key, value)
    with pytest.raises(PatroniUnavailable):
        view_of(EtcdPatroni(etcd_url(), prefix=prefix))


def test_an_unreachable_etcd_is_unavailable_and_nothing_else() -> None:
    with pytest.raises(PatroniUnavailable):
        view_of(EtcdPatroni("http://127.0.0.1:1", timeout=1.0))


def test_lag_of_the_live_cluster_is_zero_for_both_members() -> None:
    prefix = new_prefix()
    seed(prefix)
    view = view_of(EtcdPatroni(etcd_url(), prefix=prefix))
    assert view.lag("birch") == 0
    assert view.lag("willow") == 0


# --- ClusterView.lag -------------------------------------------------------------------------------------------------

def member(name: str, wal: int | None) -> Member:
    return Member(name, "replica", "running", 8, wal, "streaming", "http://10.0.0.1:8008/patroni")


def cluster(leader: str | None, **wals: int | None) -> ClusterView:
    return ClusterView(leader, {n: member(n, w) for n, w in wals.items()}, ())


@given(leader=st.integers(0, 2**40), behind=st.integers(0, 2**30))
def test_lag_is_the_leaders_position_minus_the_members(leader: int, behind: int) -> None:
    view = cluster("a", a=leader, b=max(0, leader - behind))
    assert view.lag("b") == min(behind, leader)
    assert view.lag("a") == 0


def test_lag_is_unknown_without_a_leader() -> None:
    assert cluster(None, a=10, b=5).lag("b") is None


def test_lag_is_unknown_when_either_position_is_unknown() -> None:
    assert cluster("a", a=None, b=5).lag("b") is None
    assert cluster("a", a=10, b=None).lag("b") is None


def test_lag_is_unknown_when_the_leader_has_no_member_entry() -> None:
    assert cluster("ghost", b=5).lag("b") is None


# --- switchover ------------------------------------------------------------------------------------------------------

class Rest:
    """A REST API that answers `status` (or fails to connect), recording what it was sent."""

    def __init__(self, status: int = 200, fail: bool = False) -> None:
        self.status, self.fail = status, fail
        self.requests: list[httpx2.Request] = []

    def transport(self) -> httpx2.MockTransport:
        def handler(request: httpx2.Request) -> httpx2.Response:
            self.requests.append(request)
            if self.fail:
                raise httpx2.ConnectError("refused", request=request)
            return httpx2.Response(self.status, text="Successfully switched over" if self.status == 200 else "no")
        return httpx2.MockTransport(handler)


def switch(rest: Rest, leader: str = "willow", candidate: str = "birch") -> bool:
    prefix = new_prefix()
    seed(prefix)
    patroni = EtcdPatroni(etcd_url(), prefix=prefix, auth=("patroni", "s3cret"), rest_transport=rest.transport())
    return asyncio.run(patroni.switchover(leader, candidate))


def test_switchover_posts_to_the_leaders_api_with_basic_auth() -> None:
    rest = Rest(200)
    assert switch(rest) is True
    assert len(rest.requests) == 1
    request = rest.requests[0]
    assert request.method == "POST"
    assert str(request.url) == "http://10.99.0.222:8008/switchover"
    assert json.loads(request.content) == {"leader": "willow", "candidate": "birch"}
    expected = "Basic " + base64.b64encode(b"patroni:s3cret").decode()
    assert request.headers["Authorization"] == expected


def test_switchover_goes_to_the_named_leaders_host() -> None:
    rest = Rest(200)
    assert switch(rest, leader="birch", candidate="willow") is True
    assert str(rest.requests[0].url) == "http://10.99.0.223:8008/switchover"
    assert json.loads(rest.requests[0].content) == {"leader": "birch", "candidate": "willow"}


@pytest.mark.parametrize("status", [412, 503, 500, 404, 401])
def test_a_refusal_is_false_and_not_retried(status: int) -> None:
    rest = Rest(status)
    assert switch(rest) is False
    assert len(rest.requests) == 1


def test_a_connection_error_is_false_not_raised() -> None:
    assert switch(Rest(fail=True)) is False


def test_an_unknown_leader_member_is_false_and_nothing_is_sent() -> None:
    rest = Rest(200)
    assert switch(rest, leader="ghost") is False
    assert rest.requests == []


def test_an_unreachable_etcd_makes_switchover_false_not_raised() -> None:
    rest = Rest(200)
    patroni = EtcdPatroni("http://127.0.0.1:1", timeout=1.0, rest_transport=rest.transport())
    assert asyncio.run(patroni.switchover("willow", "birch")) is False
    assert rest.requests == []

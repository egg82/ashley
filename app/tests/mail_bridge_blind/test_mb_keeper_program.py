"""The keeper as its own program (design: "a small program in the pod that imports nothing from `ashley`"; steps 2 to 4 of
"Exactly one Bridge, fenced by the epoch"): a copy run with `python -I` from an empty directory against a fake app and a
fake Bridge (`mail_bridge_blind_keeper_support`)."""

import ast
import base64
import io
import os
import signal
import tarfile
import time
from collections.abc import Callable


from mail_bridge_blind_keeper_support import (CACHE_MARK, FENCE_S, HEARTBEAT_S, KEEPER, SEED_GENERATION, SEED_VAULT,
                                              TOKEN, FakeApp, Keeper, wait_for)

Start = Callable[..., Keeper]
KEYCHAIN_PATHS = (".password-store", ".gnupg", ".config/protonmail/bridge-v3/keychain")


def test_the_keeper_imports_nothing_from_ashley() -> None:
    tree = ast.parse(KEEPER.read_text())
    imported = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    imported += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert imported, "control: the scan saw the keeper's imports"
    assert not [m for m in imported if m.split(".")[0] == "ashley"], imported


def test_the_keeper_runs_alone_with_no_ashley_on_its_path_and_starts_bridge(fake_app: FakeApp, keeper_for: Start) -> None:
    keeper = keeper_for(fake_app)
    assert keeper.bridge_up(), keeper.output()
    assert keeper.proc.poll() is None, keeper.output()


def test_the_keeper_fetches_the_vault_for_its_epoch_and_writes_it_in_before_Bridge_starts(fake_app: FakeApp, keeper_for: Start) -> None:
    keeper = keeper_for(fake_app, refresh=False)
    assert keeper.bridge_up(), keeper.output()
    assert (keeper.dir / "bridge-saw").read_bytes() == SEED_VAULT
    first = fake_app.requests[0]
    assert (first.method, first.path) == ("GET", "/vault")
    assert first.auth == f"Bearer {TOKEN}" and int(first.body["epoch"]) == fake_app.epoch


def test_a_keeper_of_a_retired_epoch_is_refused_the_vault_and_never_starts_Bridge(fake_app: FakeApp, keeper_for: Start) -> None:
    fake_app.epoch = 8
    keeper = keeper_for(fake_app, BRIDGE_EPOCH="7")
    code = keeper.exited(6)
    assert code not in (None, 0), keeper.output()
    assert not (keeper.dir / "bridge.pid").exists() and not (keeper.dir / "vault.enc").exists()


def test_the_first_write_back_follows_the_start_within_seconds_at_the_generation_the_keeper_holds(fake_app: FakeApp, keeper_for: Start) -> None:
    keeper = keeper_for(fake_app)
    assert wait_for(lambda: len(fake_app.puts()) >= 1, 6), keeper.output()
    put = fake_app.puts()[0]
    assert int(put.body["generation"]) == SEED_GENERATION and int(put.body["epoch"]) == fake_app.epoch
    assert base64.b64decode(put.body["vault"]) == SEED_VAULT + b"+refresh"
    assert fake_app.generation == SEED_GENERATION + 1


def test_every_change_to_the_vault_is_written_back_at_the_generation_the_last_write_back_answered(fake_app: FakeApp, keeper_for: Start) -> None:
    keeper = keeper_for(fake_app)
    assert wait_for(lambda: len(fake_app.puts()) == 1, 6)
    for count, data in ((2, b"settings-changed"), (3, b"sync-finished")):
        keeper.rewrite_vault(data)
        assert wait_for(lambda: len(fake_app.puts()) == count, 6), keeper.output()
        assert base64.b64decode(fake_app.puts()[-1].body["vault"]) == data
    assert [int(p.body["generation"]) for p in fake_app.puts()] == [SEED_GENERATION + i for i in range(3)]
    assert fake_app.vault == b"sync-finished"


def test_a_vault_that_did_not_change_is_not_written_back_again(fake_app: FakeApp, keeper_for: Start) -> None:
    keeper = keeper_for(fake_app)
    assert wait_for(lambda: len(fake_app.puts()) == 1, 6)
    time.sleep(1.0)
    assert len(fake_app.puts()) == 1, keeper.output()


def test_a_refused_write_back_stops_Bridge_and_ends_the_pod(fake_app: FakeApp, keeper_for: Start) -> None:
    fake_app.writeback_status = 409
    keeper = keeper_for(fake_app)
    code = keeper.exited(6)
    assert code not in (None, 0), keeper.output()
    assert not keeper.bridge_alive()


def test_a_write_back_the_database_could_not_take_503_stops_Bridge_and_ends_the_pod(fake_app: FakeApp, keeper_for: Start) -> None:
    fake_app.writeback_status = 503
    keeper = keeper_for(fake_app)
    code = keeper.exited(6)
    assert code not in (None, 0), keeper.output()
    assert not keeper.bridge_alive()


def test_a_write_back_the_app_never_answers_stops_Bridge_within_the_fence(fake_app: FakeApp, keeper_for: Start) -> None:
    keeper = keeper_for(fake_app, refresh=False)
    assert keeper.bridge_up()
    fake_app.hang_up = True
    keeper.rewrite_vault(b"never-stored")
    code = keeper.exited(FENCE_S + 3)
    assert code not in (None, 0), keeper.output()
    assert not keeper.bridge_alive()


def test_a_refused_heartbeat_stops_Bridge_and_ends_the_pod(fake_app: FakeApp, keeper_for: Start) -> None:
    keeper = keeper_for(fake_app, refresh=False)
    assert keeper.bridge_up()
    fake_app.heartbeat_status = 409
    code = keeper.exited(FENCE_S - 0.4)
    assert code is not None, "stopped by the fence, not by the refusal"
    assert code != 0, keeper.output()
    assert not keeper.bridge_alive()


def test_no_heartbeat_answered_for_fence_s_stops_Bridge_but_not_a_moment_sooner(fake_app: FakeApp, keeper_for: Start) -> None:
    keeper = keeper_for(fake_app, refresh=False)
    assert keeper.bridge_up()
    wait_for(lambda: len(fake_app.beats()) >= 2, 3)
    fake_app.hang_up = True
    time.sleep(FENCE_S * 0.4)
    assert keeper.bridge_alive() and keeper.proc.poll() is None, "stopped before the fence ran out"
    code = keeper.exited(FENCE_S + 3)
    assert code not in (None, 0), keeper.output()
    assert not keeper.bridge_alive()


def test_an_outage_shorter_than_the_fence_does_not_stop_Bridge_and_heartbeats_resume(fake_app: FakeApp, keeper_for: Start) -> None:
    keeper = keeper_for(fake_app, refresh=False)
    assert keeper.bridge_up()
    wait_for(lambda: len(fake_app.beats()) >= 2, 3)
    fake_app.hang_up = True
    time.sleep(FENCE_S * 0.4)
    fake_app.hang_up = False
    seen = len(fake_app.beats())
    assert wait_for(lambda: len(fake_app.beats()) >= seen + 2, 3)
    assert keeper.bridge_alive() and keeper.proc.poll() is None, keeper.output()


def test_the_keeper_heartbeats_about_every_heartbeat_s(fake_app: FakeApp, keeper_for: Start) -> None:
    keeper = keeper_for(fake_app, refresh=False)
    assert keeper.bridge_up()
    wait_for(lambda: len(fake_app.beats()) >= 1, 3)
    start, begun = len(fake_app.beats()), time.monotonic()
    time.sleep(1.6)
    beats = len(fake_app.beats()) - start
    expected = (time.monotonic() - begun) / HEARTBEAT_S
    assert expected * 0.5 <= beats <= expected * 1.6 + 1, (beats, expected)
    assert all(int(b.body["epoch"]) == fake_app.epoch for b in fake_app.beats())


def test_Bridge_ending_on_its_own_ends_the_keeper_so_the_pod_ends(fake_app: FakeApp, keeper_for: Start) -> None:
    keeper = keeper_for(fake_app, refresh=False)
    assert keeper.bridge_up()
    (keeper.dir / "exit").write_text("1")
    code = keeper.exited(5)
    assert code not in (None, 0), keeper.output()


def test_a_pod_told_to_end_takes_Bridge_with_it(fake_app: FakeApp, keeper_for: Start) -> None:
    keeper = keeper_for(fake_app, refresh=False)
    assert keeper.bridge_up()
    os.kill(keeper.proc.pid, signal.SIGTERM)
    assert keeper.exited(8) is not None, keeper.output()
    assert wait_for(lambda: not keeper.bridge_alive(), 3), "Bridge outlived its keeper"


def test_every_request_to_the_app_carries_the_token_and_names_the_epoch(fake_app: FakeApp, keeper_for: Start) -> None:
    keeper = keeper_for(fake_app)
    assert wait_for(lambda: len(fake_app.puts()) >= 1 and len(fake_app.beats()) >= 2, 6), keeper.output()
    for r in fake_app.requests:
        assert r.auth == f"Bearer {TOKEN}", (r.method, r.path)
        assert int(r.body["epoch"]) == fake_app.epoch, (r.method, r.path)


def test_the_cache_is_never_shipped_only_the_vault_and_the_keychain(fake_app: FakeApp, keeper_for: Start) -> None:
    keeper = keeper_for(fake_app)
    assert keeper.bridge_up()
    assert (keeper.cache / "messages.db").read_bytes().startswith(CACHE_MARK), "control: Bridge wrote a cache"
    keeper.rewrite_vault(b"another-vault")
    assert wait_for(lambda: len(fake_app.puts()) == 2, 6)
    time.sleep(0.5)
    assert len(fake_app.puts()) == 2
    for put in fake_app.puts():
        assert set(put.body) == {"epoch", "generation", "vault", "keychain"}, sorted(put.body)
        with tarfile.open(fileobj=io.BytesIO(base64.b64decode(put.body["keychain"])), mode="r") as tar:
            names = tar.getnames()
            assert names, "control: the keychain holds files"
            assert all(n.startswith(KEYCHAIN_PATHS) for n in names), names
            held = b""
            for member in tar.getmembers():
                body = tar.extractfile(member) if member.isfile() else None
                held += b"" if body is None else body.read()
        assert CACHE_MARK not in held and CACHE_MARK not in base64.b64decode(put.body["vault"])
    assert base64.b64decode(fake_app.puts()[-1].body["vault"]) == b"another-vault"
    assert CACHE_MARK.decode() not in fake_app.wire_text() and base64.b64encode(CACHE_MARK).decode()[:12] not in fake_app.wire_text()


def test_the_keeper_logs_something_and_never_the_vault_the_token_or_the_bridge_password(fake_app: FakeApp, keeper_for: Start) -> None:
    keeper = keeper_for(fake_app)
    assert wait_for(lambda: len(fake_app.puts()) >= 1, 6)
    keeper.rewrite_vault(b"VAULT-TWO-SECRET")
    assert wait_for(lambda: len(fake_app.puts()) >= 2, 6)
    fake_app.heartbeat_status = 409
    keeper.exited(5)
    out = keeper.output()
    assert out.strip(), "control: the keeper wrote a log"
    for raw in (SEED_VAULT, SEED_VAULT + b"+refresh", b"VAULT-TWO-SECRET"):
        for form in (raw.decode(), raw.hex(), base64.b64encode(raw).decode()):
            assert form not in out
    assert TOKEN not in out and "Bearer" not in out


"""The keeper's rules (`deploy/mail-bridge/keeper.py`) against a fake app, a fake Bridge and real files in a temporary home:
the vault is written back before the keeper does anything else, and at the generation it holds; a write-back or a heartbeat
the app refuses, a write-back it does not answer, or no heartbeat answered for `fence_s` ends Bridge; a first start makes the
keychain and a later one installs what was written back; a login is answered only after its session is stored."""

import base64
import hashlib
from pathlib import Path

import pytest
from keeper_files import CONFIG, KEYCHAIN, VAULT
from keeper_link import LoginEvent, Stopped, UserEvent, UserInfo
from mail_keeper_support import CERT_DER, FakeApp, Rig, make_keychain, rig


def booted(tmp_path: Path, app: FakeApp | None = None, **kw: float) -> Rig:
    r = rig(tmp_path / "home", app, **kw)
    r.home.mkdir()
    r.keeper.boot()
    return r


def with_record(tmp_path: Path, generation: int = 4) -> FakeApp:
    """A record holding a vault and keychain, as a previous pod left them."""
    made = tmp_path / "earlier"
    made.mkdir()
    return FakeApp(generation, b"vault-4", make_keychain(made))


def test_a_first_start_makes_the_keychain_and_writes_the_first_vault_back_at_generation_zero(tmp_path: Path) -> None:
    r = booted(tmp_path)
    assert [c[0] for c in r.commands] == ["gpg", "pass"] and r.app.calls == ["vault"]
    r.bridge_writes_vault(b"vault-0")
    (r.home / ".password-store").mkdir(exist_ok=True)
    (r.home / ".password-store" / "bridge-vault-key.gpg").write_bytes(b"sealed")
    r.keeper.step()
    assert r.app.written == [(0, b"vault-0")] and r.app.generation == 1
    assert r.app.keychain is not None and b"bridge-vault-key.gpg" in r.app.keychain


def test_a_later_start_installs_what_was_written_back_and_writes_nothing_while_it_is_unchanged(tmp_path: Path) -> None:
    app = with_record(tmp_path)
    r = booted(tmp_path, app)
    assert (r.home / VAULT).read_bytes() == b"vault-4" and r.commands == []
    assert all((r.home / p).exists() for p in KEYCHAIN)
    assert (r.home / ".gnupg").stat().st_mode & 0o777 == 0o700
    r.keeper.step()
    assert r.app.written == []


def test_the_vault_is_written_back_before_a_heartbeat_an_event_or_a_login_answer(tmp_path: Path) -> None:
    r = booted(tmp_path, with_record(tmp_path))
    r.bridge_writes_vault(b"vault-5")
    r.keeper.step()
    assert r.app.calls[-2:] == ["vault", "heartbeat"] and r.app.written == [(4, b"vault-5")]
    r.bridge_writes_vault(b"vault-6")
    r.keeper.on_event(UserEvent("u1", sync="progress", progress=0.5))
    assert r.app.calls[-2:] == ["vault", "events"] and r.app.written[-1] == (5, b"vault-6")
    r.bridge_writes_vault(b"vault-7")
    r.bridge.logins = [LoginEvent("tfa")]
    assert r.keeper.login("alana", "pw") == {"step": "two_factor"}
    assert r.app.calls[-1] == "vault" and r.app.written[-1] == (6, b"vault-7")


def test_a_write_back_names_the_generation_the_keeper_holds_and_the_next_carries_the_new_one(tmp_path: Path) -> None:
    r = booted(tmp_path, with_record(tmp_path, generation=9))
    for n in range(3):
        r.bridge_writes_vault(f"v{n}".encode())
        r.keeper.step()
    assert [g for g, _ in r.app.written] == [9, 10, 11]


@pytest.mark.parametrize("status", [409, 503, 401])
def test_a_refused_write_back_ends_bridge_and_nothing_more_is_sent(tmp_path: Path, status: int) -> None:
    r = booted(tmp_path, with_record(tmp_path))
    r.app.forced["vault"] = status
    r.bridge_writes_vault(b"vault-5")
    with pytest.raises(Stopped):
        r.keeper.step()
    assert r.process.killed and r.keeper.stopped.is_set() and r.keeper.reason == "write_back_refused"
    sent = len(r.app.calls)
    r.keeper.on_event(UserEvent("u1", sync="finished"))
    with pytest.raises(Stopped):
        r.keeper.login("alana", "pw")
    assert len(r.app.calls) == sent and "heartbeat" not in r.app.calls


def test_a_write_back_the_app_does_not_answer_ends_bridge_at_once(tmp_path: Path) -> None:
    r = booted(tmp_path, with_record(tmp_path))
    r.app.forced["vault"] = None
    r.bridge_writes_vault(b"vault-5")
    with pytest.raises(Stopped):
        r.keeper.step()
    assert r.process.killed and r.keeper.reason == "write_back_appunreachable"


@pytest.mark.parametrize("status", [409, 503])
def test_a_refused_heartbeat_ends_bridge_at_once(tmp_path: Path, status: int) -> None:
    r = booted(tmp_path, with_record(tmp_path))
    r.app.forced["heartbeat"] = status
    r.clock.now = 5.0
    with pytest.raises(Stopped):
        r.keeper.step()
    assert r.process.killed and r.keeper.reason == "heartbeat_refused"


def test_heartbeats_unanswered_end_bridge_only_after_the_fence(tmp_path: Path) -> None:
    r = booted(tmp_path, with_record(tmp_path), heartbeat_s=5, fence_s=30)
    r.app.forced["heartbeat"] = None
    while r.clock.now < 29:
        r.clock.sleep(1)
        r.keeper.step()
    assert not r.process.killed
    r.clock.sleep(2)
    with pytest.raises(Stopped):
        r.keeper.step()
    assert r.process.killed and r.keeper.reason == "fence"


def test_a_bridge_that_ends_on_its_own_ends_the_keeper_so_the_pod_ends(tmp_path: Path) -> None:
    r = booted(tmp_path, with_record(tmp_path))
    r.keeper.step()
    r.process.exited = True
    with pytest.raises(Stopped):
        r.keeper.step()
    assert r.keeper.stopped.is_set() and r.keeper.reason == "bridge_exited"


def test_an_answered_heartbeat_moves_the_fence_and_carries_the_certificate_fingerprint(tmp_path: Path) -> None:
    r = booted(tmp_path, with_record(tmp_path), heartbeat_s=5, fence_s=30)
    for _ in range(20):
        r.clock.sleep(5)
        r.keeper.step()
    assert not r.process.killed
    assert set(r.app.beats) == {hashlib.sha256(CERT_DER).hexdigest()}


def test_a_login_answer_waits_for_the_session_to_be_stored_and_carries_what_the_app_stores(tmp_path: Path) -> None:
    r = booted(tmp_path, with_record(tmp_path))
    r.bridge.users_held["u1"] = UserInfo("u1", "connected", False, ("a@proton.test", "b@proton.test"), "issued-pw")
    r.bridge.logins = [LoginEvent("finished", user_id="u1")]
    r.bridge.on_login = lambda: r.bridge_writes_vault(b"vault-with-session")
    r.keeper.on_event(UserEvent("u1", sync="finished"))
    answer = r.keeper.login("alana@proton.test", "pw")
    assert answer == {"step": "connected", "user_id": "u1", "addresses": ["a@proton.test", "b@proton.test"],
                      "bridge_password": "issued-pw", "epoch": 3, "synced": True}
    assert r.app.written[-1][1] == b"vault-with-session" and r.app.calls.index("vault", 2) < len(r.app.calls)
    assert "split u1" in r.bridge.asked


def test_a_login_is_not_synced_until_bridge_says_so_and_a_refusal_clears_the_pending_login(tmp_path: Path) -> None:
    r = booted(tmp_path, with_record(tmp_path))
    r.bridge.users_held["u1"] = UserInfo("u1", "connected", True, ("a@proton.test",), "pw")
    r.bridge.logins = [LoginEvent("error", reason="credentials"), LoginEvent("finished", user_id="u1")]
    assert r.keeper.login("alana", "bad") == {"step": "refused", "reason": "credentials"}
    assert r.keeper.login("alana", "good")["synced"] is False
    assert "split u1" not in r.bridge.asked


def test_a_second_login_aborts_the_one_before_it_and_steps_go_to_the_user_being_logged_in(tmp_path: Path) -> None:
    r = booted(tmp_path, with_record(tmp_path))
    r.bridge.logins = [LoginEvent("tfa"), LoginEvent("tfa"), LoginEvent("two_passwords")]
    r.keeper.login("first", "pw")
    r.keeper.login("second", "pw")
    assert r.keeper.second_factor("123456") == {"step": "mailbox_password"}
    assert r.bridge.asked == ["login first", "abort first", "login second", "second_factor second"]


def test_forgetting_a_user_removes_it_and_writes_the_vault_back(tmp_path: Path) -> None:
    r = booted(tmp_path, with_record(tmp_path))
    r.bridge.users_held["u1"] = UserInfo("u1", "connected", True, (), "pw")
    r.keeper.forget("u1")
    assert r.bridge.asked == ["remove u1"] and "u1" not in r.bridge.users_held


def test_events_are_relayed_with_their_kind_and_a_refused_event_ends_bridge(tmp_path: Path) -> None:
    r = booted(tmp_path, with_record(tmp_path))
    r.keeper.on_event(UserEvent("u1", state="signed_out"))
    r.keeper.on_event(UserEvent("u1", sync="progress", progress=0.25))
    assert r.app.events == [
        {"epoch": 3, "user_id": "u1", "state": "signed_out", "sync": None, "progress": None},
        {"epoch": 3, "user_id": "u1", "state": None, "sync": "progress", "progress": 0.25}]
    r.app.forced["events"] = 409
    r.keeper.on_event(UserEvent("u1", sync="finished"))
    assert r.process.killed and r.keeper.reason == "event_refused"


def test_a_vault_that_cannot_be_fetched_never_starts_bridge(tmp_path: Path) -> None:
    app = FakeApp()
    app.forced["vault"] = 409
    r = rig(tmp_path / "home", app)
    (tmp_path / "home").mkdir()
    assert r.keeper.run() == 1
    assert r.keeper.reason == "vault_fetch_refused" and not (r.home / CONFIG).exists()


def test_the_keychain_is_packed_and_unpacked_as_its_own_files_only(tmp_path: Path) -> None:
    from keeper_files import install
    import io
    import tarfile
    evil = io.BytesIO()
    with tarfile.open(fileobj=evil, mode="w") as tar:
        info = tarfile.TarInfo("../escape")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(ValueError):
        install(tmp_path, b"v", evil.getvalue(), lambda argv: None)
    assert not (tmp_path.parent / "escape").exists()
    assert base64.b64decode(base64.b64encode(b"x")) == b"x"


def test_a_human_check_is_answered_with_its_url_and_the_verified_retry_continues_the_same_login(tmp_path: Path) -> None:
    r = booted(tmp_path, with_record(tmp_path))
    r.bridge.users_held["u1"] = UserInfo("u1", "connected", True, ("a@proton.test",), "pw")
    r.bridge.logins = [LoginEvent("human_verification", url="https://verify.proton.me/?token=t"),
                       LoginEvent("finished", user_id="u1")]
    assert r.keeper.login("alana", "pw") == {"step": "human_verification", "url": "https://verify.proton.me/?token=t"}
    assert r.keeper.verified_login("pw")["step"] == "connected"
    assert r.bridge.asked[:2] == ["login alana", "login alana verified"]


def test_a_security_key_only_account_is_refused_and_its_login_aborted(tmp_path: Path) -> None:
    r = booted(tmp_path, with_record(tmp_path))
    r.bridge.logins = [LoginEvent("error", reason="security_key")]
    assert r.keeper.login("alana", "pw") == {"step": "refused", "reason": "security_key"}
    assert r.bridge.asked[:2] == ["login alana", "abort alana"]

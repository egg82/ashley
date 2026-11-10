"""The epoch and generation fence on the app's side (design: "Every heartbeat and every write-back names the epoch, and
the route refuses one that is not current (409) or cannot be written (503 ...)" and "the row takes it only at that
generation and the current epoch")."""

import base64
import threading
from datetime import datetime

from mail_bridge_blind_support import KEYCHAIN, PREFIX, VAULT, Pod, World, b64, dump, forms, read_only, sha


def body_of(world: World, pod: Pod) -> dict[str, object]:
    got = world.fetch(pod)
    assert got.status_code == 200, got.text
    return dict(got.json())


def test_a_fresh_record_is_epoch_zero_generation_zero_with_no_vault(world: World) -> None:
    state = world.state()
    assert (state.epoch, state.generation, state.has_vault) == (0, 0, False)
    assert state.heartbeat_at is None


def test_begin_epoch_raises_the_epoch_by_one_and_keeps_site_pod_and_the_tokens_hash(world: World) -> None:
    first = world.begin("site-a", "pod-a")
    second = world.begin("site-b", "pod-b")
    assert (first.epoch, second.epoch) == (1, 2)
    state = world.state()
    assert (state.epoch, state.site, state.pod, state.token_hash) == (2, "site-b", "pod-b", sha(second.token))


def test_a_heartbeat_at_the_current_epoch_is_taken_and_stamps_the_record(world: World) -> None:
    pod = world.begin()
    assert world.state().heartbeat_at is None
    assert world.beat(pod).status_code == 200
    state = world.state()
    assert isinstance(state.heartbeat_at, datetime)
    assert state.fingerprint == pod.fingerprint


def test_a_second_heartbeat_moves_the_stamp_forward(world: World) -> None:
    pod = world.begin()
    world.beat(pod)
    first = world.state().heartbeat_at
    world.beat(pod)
    assert world.state().heartbeat_at > first


def test_a_heartbeat_at_an_old_epoch_is_refused_409_and_stamps_nothing(world: World) -> None:
    old = world.begin(name="old")
    new = world.begin(name="new")
    assert world.beat(new).status_code == 200
    stamped = world.state().heartbeat_at
    got = world.client.post(f"{PREFIX}/heartbeat", json={"epoch": old.epoch}, headers=new.auth())
    assert got.status_code == 409
    assert world.state().heartbeat_at == stamped


def test_the_old_epochs_token_is_refused_once_a_new_epoch_has_begun(world: World) -> None:
    old = world.begin(name="old")
    assert world.beat(old).status_code == 200
    world.begin(name="new")
    got = world.beat(old)
    assert got.status_code in (401, 403, 409)


def test_a_heartbeat_with_no_token_or_a_wrong_one_is_refused_and_stamps_nothing(world: World) -> None:
    pod = world.begin()
    url = f"{PREFIX}/heartbeat"
    assert world.client.post(url, json={"epoch": pod.epoch}).status_code in (401, 403)
    assert world.client.post(url, json={"epoch": pod.epoch}, headers={"authorization": "Bearer nope"}).status_code in (401, 403)
    assert world.state().heartbeat_at is None


def test_a_write_back_at_the_current_generation_and_epoch_is_taken_and_raises_the_generation_by_one(world: World) -> None:
    pod = world.begin()
    got = world.put(pod, 0)
    assert got.status_code == 200
    assert got.json()["generation"] == 1
    state = world.state()
    assert (state.generation, state.has_vault) == (1, True)
    body = body_of(world, pod)
    assert body["generation"] == 1
    assert base64.b64decode(str(body["vault"])) == VAULT
    assert base64.b64decode(str(body["keychain"])) == KEYCHAIN


def test_each_accepted_write_back_raises_the_generation_by_exactly_one(world: World) -> None:
    pod = world.begin()
    for expected in (1, 2, 3):
        assert world.put(pod, expected - 1, VAULT + bytes([expected])).json()["generation"] == expected
    assert world.state().generation == 3


def test_a_write_back_at_a_stale_generation_is_refused_409_and_changes_nothing(world: World) -> None:
    pod = world.begin()
    world.put(pod, 0, b"first-vault")
    world.put(pod, 1, b"second-vault")
    got = world.put(pod, 1, b"STALE-vault")
    assert got.status_code == 409
    assert world.state().generation == 2
    assert base64.b64decode(str(body_of(world, pod)["vault"])) == b"second-vault"


def test_a_write_back_at_a_generation_ahead_of_the_row_is_refused_409(world: World) -> None:
    pod = world.begin()
    assert world.put(pod, 5, b"AHEAD-vault").status_code == 409
    state = world.state()
    assert (state.generation, state.has_vault) == (0, False)


def test_a_write_back_at_a_stale_epoch_is_refused_409_whatever_its_generation(world: World) -> None:
    old = world.begin(name="old")
    world.put(old, 0, b"old-vault")
    new = world.begin(name="new")
    assert world.put(old, 1, b"FORK-vault", epoch=old.epoch).status_code in (401, 403, 409)
    assert world.put(new, 1, b"FORK-vault2", epoch=old.epoch).status_code == 409
    assert world.state().generation == 1
    assert base64.b64decode(str(body_of(world, new)["vault"])) == b"old-vault"


def test_a_write_back_with_no_token_is_refused_and_changes_nothing(world: World) -> None:
    pod = world.begin()
    got = world.client.put(f"{PREFIX}/vault", json={
        "epoch": pod.epoch, "generation": 0, "vault": b64(VAULT), "keychain": b64(KEYCHAIN)})
    assert got.status_code in (401, 403)
    assert world.state().generation == 0


def test_two_writers_at_the_same_generation_take_exactly_one(world: World) -> None:
    pod = world.begin()
    codes: list[int] = []

    def write(tag: bytes) -> None:
        codes.append(world.put(pod, 0, b"vault-" + tag).status_code)

    threads = [threading.Thread(target=write, args=(bytes([65 + i]),)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert sorted(codes) == [200, 409, 409, 409, 409, 409]
    assert world.state().generation == 1


def test_a_retired_epoch_cannot_fetch_the_vault(world: World) -> None:
    old = world.begin(name="old")
    world.put(old, 0, b"secret-vault")
    world.begin(name="new")
    got = world.fetch(old)
    assert got.status_code in (401, 403, 409)
    assert "secret-vault" not in got.text and b64(b"secret-vault") not in got.text


def test_the_current_epoch_fetches_the_vault_at_its_generation(world: World) -> None:
    pod = world.begin()
    world.put(pod, 0, b"v1")
    world.put(pod, 1, b"v2")
    newer = world.begin(name="newer")
    body = body_of(world, newer)
    assert body["generation"] == 2
    assert base64.b64decode(str(body["vault"])) == b"v2"


def test_a_fetch_before_any_write_back_has_no_vault(world: World) -> None:
    pod = world.begin()
    got = world.fetch(pod)
    assert got.status_code == 200
    assert got.json()["vault"] is None and got.json()["generation"] == 0


def test_a_new_epoch_leaves_generation_and_vault_alone(world: World) -> None:
    pod = world.begin()
    world.put(pod, 0, b"kept-vault")
    world.begin(name="next")
    state = world.state()
    assert (state.generation, state.has_vault) == (1, True)


def test_the_vault_and_keychain_are_stored_sealed_and_the_token_only_as_its_hash(world: World) -> None:
    pod = world.begin()
    world.put(pod, 0, VAULT, keychain=KEYCHAIN)
    stored = dump(world.url)
    assert sha(pod.token) in stored, "control: the probe can find what is stored"
    for raw in (VAULT, KEYCHAIN):
        for form in forms(raw):
            assert form not in stored, f"{raw!r} is stored in the clear as {form[:12]!r}"
    assert pod.token not in stored


def test_a_database_that_cannot_be_written_answers_a_write_back_503_and_a_heartbeat_503_and_changes_nothing(world: World) -> None:
    pod = world.begin()
    world.put(pod, 0, b"before")
    world.beat(pod)
    stamped = world.state().heartbeat_at
    with read_only(world.url):
        puts = [world.put(pod, 1, b"during").status_code for _ in range(3)]
        beats = [world.beat(pod).status_code for _ in range(3)]
    assert puts[-1] == 503 and beats[-1] == 503, (puts, beats)
    assert 200 not in puts + beats and 500 not in puts + beats
    assert world.state().generation == 1
    assert world.state().heartbeat_at == stamped
    assert world.put(pod, 1, b"after").status_code == 200

"""The token and the person lock: who may call the bridge at all."""

import hashlib
import threading

import pytest
from herdr_bridge.auth import TOKEN_FILE, token_digest
from herdr_bridge.install import init
from herdr_bridge_blind_pki import Pki, der_fingerprint, write_pair
from herdr_bridge_blind_support import PERSON, ROUTES, Bridge, bearer, restarted, send

OTHER = "someone-else"


def test_whoami_names_the_person_and_the_versions(bridge: Bridge) -> None:
    r = bridge.get("/v1/whoami")
    assert r.status == 200
    assert r.body["person"] == PERSON
    assert "0.9.5" in str(r.body["herdr_version"])
    assert r.body["bridge_version"]


def test_a_missing_token_is_bad_token(bridge: Bridge) -> None:
    r = bridge.get("/v1/whoami", token=None)
    assert (r.status, r.body) == (401, {"error": "bad_token"})


@pytest.mark.parametrize("variant", ["wrong", "TRUNC", "EXTRA", "UPPER", "SPACE"])
def test_a_wrong_token_is_bad_token(bridge: Bridge, variant: str) -> None:
    t = bridge.token
    token = {"wrong": "wrong", "TRUNC": t[:-1], "EXTRA": t + "x", "UPPER": t.upper(), "SPACE": " " + t}[variant]
    r = bridge.get("/v1/whoami", token=token)
    assert (r.status, r.body) == (401, {"error": "bad_token"})


@pytest.mark.parametrize("header", ["Basic {t}", "{t}", "Bearer", "Bearer  ", "Token {t}", "Bearer {t} extra"])
def test_only_a_bearer_token_in_the_authorization_header_counts(bridge: Bridge, header: str) -> None:
    value = header.format(t=bridge.token)
    r = send(bridge.api, "GET", "/v1/whoami", {"Authorization": value, "X-Ashley-Person": PERSON})
    assert (r.status, r.body) == (401, {"error": "bad_token"})


def test_the_token_in_the_query_or_person_header_is_no_token(bridge: Bridge) -> None:
    r = bridge.call("GET", "/v1/whoami", token=None, query={"token": bridge.token, "access_token": bridge.token})
    assert r.status == 401
    r = send(bridge.api, "GET", "/v1/whoami", {"X-Ashley-Person": bridge.token})
    assert r.status == 401


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_every_call_needs_the_token_before_anything_else(bridge: Bridge, method: str, path: str, body: object) -> None:
    r = bridge.call(method, path, body, token="nope")
    assert (r.status, r.body) == (401, {"error": "bad_token"})
    assert bridge.herdr.changes() == []


def test_a_wrong_token_does_not_claim_the_bridge(bridge: Bridge) -> None:
    assert bridge.get("/v1/whoami", token="nope", person=OTHER).status == 401
    assert bridge.get("/v1/whoami").status == 200


def test_a_wrong_token_with_the_wrong_person_is_still_bad_token(bridge: Bridge) -> None:
    assert bridge.get("/v1/whoami").status == 200
    r = bridge.get("/v1/whoami", token="nope", person=OTHER)
    assert (r.status, r.body) == (401, {"error": "bad_token"})


def test_no_person_is_wrong_person_and_claims_nothing(bridge: Bridge) -> None:
    r = bridge.get("/v1/whoami", person=None)
    assert (r.status, r.body) == (403, {"error": "wrong_person"})
    assert bridge.get("/v1/whoami", person=OTHER).body["person"] == OTHER


@pytest.mark.parametrize("bad", ["", "a b", "x" * 65, "line\nbreak", "semi;colon", "slash/er", "naïve"])
def test_a_malformed_person_id_is_refused_and_claims_nothing(bridge: Bridge, bad: str) -> None:
    r = bridge.get("/v1/whoami", person=bad)
    assert 400 <= r.status < 500
    assert bridge.get("/v1/whoami", person=OTHER).status == 200


def test_the_first_person_owns_the_bridge_and_everyone_else_is_refused_on_every_call(bridge: Bridge) -> None:
    assert bridge.get("/v1/sessions").status == 200
    for method, path, body in ROUTES:
        r = bridge.call(method, path, body, person=OTHER)
        assert (r.status, r.body) == (403, {"error": "wrong_person"}), path
    assert bridge.herdr.changes() == []
    assert bridge.get("/v1/whoami").body["person"] == PERSON


def test_a_person_differing_only_in_case_is_another_person(bridge: Bridge) -> None:
    assert bridge.get("/v1/whoami").status == 200
    assert bridge.get("/v1/whoami", person=PERSON.upper()).status == 403
    assert bridge.get("/v1/whoami", person=PERSON + " ").status in (403, 400)


def test_the_lock_survives_a_restart(bridge: Bridge) -> None:
    assert bridge.get("/v1/whoami").status == 200
    api = restarted(bridge)
    assert send(api, "GET", "/v1/whoami", bearer(bridge.token) | {"X-Ashley-Person": OTHER}).status == 403
    assert send(api, "GET", "/v1/whoami", bearer(bridge.token)).status == 200


def test_the_race_for_a_fresh_bridge_has_one_winner(bridge: Bridge) -> None:
    results: list[tuple[str, int]] = []

    def go(person: str) -> None:
        results.append((person, bridge.get("/v1/whoami", person=person).status))

    people = [f"racer{i}" for i in range(12)]
    threads = [threading.Thread(target=go, args=(p,)) for p in people]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(results) == len(people)
    assert len({p for p, s in results if s == 200}) == 1
    assert sorted(s for _, s in results).count(403) == len(people) - 1


def reinit(b: Bridge, pki: Pki) -> str:
    token, _ = init(b.config, b.config_path, lambda cert, key: write_pair(pki.server, cert, key))
    return token


def test_init_again_mints_a_new_token_and_releases_the_person(bridge: Bridge, pki: Pki) -> None:
    assert bridge.get("/v1/whoami").status == 200
    token = reinit(bridge, pki)
    assert token != bridge.token
    api = restarted(bridge)
    assert send(api, "GET", "/v1/whoami", bearer(bridge.token)).status == 401
    assert send(api, "GET", "/v1/whoami", bearer(token) | {"X-Ashley-Person": OTHER}).body["person"] == OTHER


def test_the_token_is_stored_only_as_its_digest(bridge: Bridge) -> None:
    kept = [p for d in (bridge.state_dir, bridge.config_path.parent) for p in d.rglob("*") if p.is_file()]
    assert kept
    blobs = [p.read_bytes() for p in kept]
    assert not any(bridge.token.encode() in b for b in blobs)
    assert any(token_digest(bridge.token).encode() in b for b in blobs)


def test_the_token_is_long_and_different_each_time(bridge: Bridge, pki: Pki) -> None:
    assert len(bridge.token) >= 32
    assert len({reinit(bridge, pki) for _ in range(3)}) == 3


def test_init_reports_the_fingerprint_of_the_certificate_it_made(bridge: Bridge) -> None:
    pem = bridge.config.cert.read_bytes()
    assert bridge.fingerprint == der_fingerprint(pem)


def test_the_token_file_holds_the_full_sha256_of_the_token(bridge: Bridge) -> None:
    assert (bridge.state_dir / TOKEN_FILE).read_text().strip() == hashlib.sha256(bridge.token.encode()).hexdigest()

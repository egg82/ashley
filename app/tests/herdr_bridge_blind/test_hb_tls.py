"""Mutual TLS: no client certificate from the ashley-bridges CA, no answer."""

import hashlib
import ssl
from pathlib import Path

import pytest
from herdr_bridge_blind_pki import Pair, Pki, der_fingerprint
from herdr_bridge_blind_support import Bridge
from herdr_bridge_blind_tls import auth, client_context, request, serving


def refused_clients(pki: Pki) -> dict[str, Pair | None]:
    return {
        "none": None,
        "other_ca": pki.foreign_client,
        "expired": pki.expired_client,
        "self_signed": pki.self_signed_client,
        "bridge_own_cert": pki.server,
    }


@pytest.mark.parametrize("who", ["none", "other_ca", "expired", "self_signed", "bridge_own_cert"])
def test_a_client_the_ca_did_not_sign_gets_no_answer_and_reaches_nothing(
    bridge: Bridge, pki: Pki, tmp_path: Path, who: str
) -> None:
    with serving(bridge) as port:
        ctx = client_context(tmp_path, refused_clients(pki)[who])
        assert request(port, ctx, "GET", "/v1/whoami", auth(bridge)) is None
        assert request(port, ctx, "GET", "/v1/sessions", auth(bridge)) is None
    assert bridge.herdr.calls == []
    assert all(line.startswith("call=connection ") for line in bridge.log.lines), bridge.log.lines


def test_the_ca_signed_client_is_answered_over_tls_1_3(bridge: Bridge, pki: Pki, tmp_path: Path) -> None:
    with serving(bridge) as port:
        got = request(port, client_context(tmp_path, pki.client), "GET", "/v1/whoami", auth(bridge))
    assert got is not None and got.status == 200
    assert got.tls_version == "TLSv1.3"
    assert got.body["person"] == "person-zq9"


def test_a_valid_certificate_still_needs_the_token(bridge: Bridge, pki: Pki, tmp_path: Path) -> None:
    with serving(bridge) as port:
        ctx = client_context(tmp_path, pki.client)
        got = request(port, ctx, "GET", "/v1/whoami", {"X-Ashley-Person": "person-zq9"})
        wrong = request(port, ctx, "GET", "/v1/whoami", auth(bridge) | {"Authorization": "Bearer nope"})
    assert got is not None and (got.status, got.body) == (401, {"error": "bad_token"})
    assert wrong is not None and wrong.status == 401


def test_a_client_limited_to_tls_1_2_gets_no_answer(bridge: Bridge, pki: Pki, tmp_path: Path) -> None:
    with serving(bridge) as port:
        ctx = client_context(tmp_path, pki.client, ssl.TLSVersion.TLSv1_2)
        assert request(port, ctx, "GET", "/v1/whoami", auth(bridge)) is None
    assert bridge.herdr.calls == []


def test_plain_http_gets_no_answer_and_reaches_nothing(bridge: Bridge) -> None:
    with serving(bridge) as port:
        assert request(port, None, "GET", "/v1/whoami", auth(bridge)) is None
        assert request(port, None, "POST", "/v1/sessions", auth(bridge), b'{"dir":"/tmp","label":"abc"}') is None
    assert bridge.herdr.calls == []


def test_the_server_presents_the_certificate_whose_fingerprint_init_printed(
    bridge: Bridge, pki: Pki, tmp_path: Path
) -> None:
    import socket

    with serving(bridge) as port:
        ctx = client_context(tmp_path, pki.client)
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw, ctx.wrap_socket(raw) as tls:
            der = tls.getpeercert(binary_form=True)
    assert der is not None
    assert hashlib.sha256(der).hexdigest() == bridge.fingerprint
    assert bridge.fingerprint == der_fingerprint(bridge.config.cert.read_bytes())


def test_refused_handshakes_do_not_stop_the_server_or_log_the_client_address(
    bridge: Bridge, pki: Pki, tmp_path: Path
) -> None:
    with serving(bridge) as port:
        for pair in (None, pki.foreign_client, pki.expired_client):
            request(port, client_context(tmp_path, pair), "GET", "/v1/whoami", auth(bridge))
        request(port, None, "GET", "/", {})
        good = request(port, client_context(tmp_path, pki.client), "GET", "/v1/whoami", auth(bridge))
    assert good is not None and good.status == 200
    assert "127.0.0.1" not in bridge.log.text()
    assert "localhost" not in bridge.log.text()


def test_headers_are_case_insensitive_on_the_wire(bridge: Bridge, pki: Pki, tmp_path: Path) -> None:
    with serving(bridge) as port:
        hdrs = {"authorization": f"Bearer {bridge.token}", "x-ashley-person": "person-zq9"}
        got = request(port, client_context(tmp_path, pki.client), "GET", "/v1/whoami", hdrs)
    assert got is not None and got.status == 200


def test_a_query_string_travels_and_a_start_works_end_to_end(bridge: Bridge, pki: Pki, tmp_path: Path) -> None:
    a = bridge.add("alpha")
    bridge.mkdir("proj")
    with serving(bridge) as port:
        ctx = client_context(tmp_path, pki.client)
        read = request(port, ctx, "GET", f"/v1/sessions/{a.session_id}/read?lines=3", auth(bridge))
        bad = request(port, ctx, "GET", f"/v1/sessions/{a.session_id}/read?lines=9999", auth(bridge))
        out = request(port, ctx, "POST", "/v1/sessions", auth(bridge), b'{"dir": "%s/proj", "label": "wired"}' % bridge.root.as_posix().encode())
        outside = request(port, ctx, "POST", "/v1/sessions", auth(bridge), b'{"dir": "/etc", "label": "wired"}')
    assert read is not None and read.status == 200
    assert bad is not None and bad.status == 400
    assert out is not None and out.status in (200, 201)
    assert outside is not None and (outside.status, outside.body) == (403, {"error": "dir_not_allowed"})


def test_an_oversized_or_garbled_request_is_survived(bridge: Bridge, pki: Pki, tmp_path: Path) -> None:
    with serving(bridge) as port:
        ctx = client_context(tmp_path, pki.client)
        a = request(port, ctx, "POST", "/v1/sessions", auth(bridge), b"{" + b"x" * 3_000_000)
        b = request(port, ctx, "BREW", "/v1/whoami", auth(bridge))
        c = request(port, ctx, "GET", "/v1/whoami?" + "a=b&" * 20000, auth(bridge))
        good = request(port, ctx, "GET", "/v1/whoami", auth(bridge))
    for r in (a, b, c):
        assert r is None or r.status >= 400 or r.status == 200
    assert a is None or a.status >= 400
    assert good is not None and good.status == 200
    assert bridge.herdr.changes() == []

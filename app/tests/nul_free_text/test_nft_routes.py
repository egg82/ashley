"""A NUL (U+0000) in a free-text field of a request is a 422, never a 500 or a 503: no text column holds one. Each case
is also sent with the NUL left out, so a 503 from an unwired service cannot pass for the refusal."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from nul_free_text_support import NUL, NUL_PATH, ORIGIN

Case = tuple[str, str, dict[str, Any] | None]

CASES: dict[str, Callable[[str, str], Case]] = {
    "lexicon_spoken": lambda nul, path: ("PUT", "/api/lexicon/word", {"spoken": "a" + nul}),
    "lexicon_real_removed": lambda nul, path: ("DELETE", f"/api/lexicon/wo{path}rd", None),
    "connection_resource_ref": lambda nul, path: ("PATCH", f"/api/connections/1/resources/a{path}", {"shared": True}),
    "skill_kind_rolled_back": lambda nul, path: ("POST", f"/api/skills/a{path}/rollback", {"to_version": 0}),
    "skill_kind_proposal_approved": lambda nul, path: ("POST", f"/api/skills/a{path}/proposals/1/approve", None),
    "skill_kind_proposal_declined": lambda nul, path: ("POST", f"/api/skills/a{path}/proposals/1/decline", None),
}


def send(client: TestClient, case: str, nul: str, nul_path: str) -> Response:
    method, path, body = CASES[case](nul, nul_path)
    return client.request(method, path, json=body, headers=ORIGIN) if body is not None \
        else client.request(method, path, headers=ORIGIN)


@pytest.mark.parametrize("case", CASES)
def test_the_same_request_without_the_nul_is_answered(client: TestClient, case: str) -> None:
    assert send(client, case, "", "").status_code < 500


@pytest.mark.parametrize("case", CASES)
def test_a_nul_in_a_request_is_refused_as_invalid(client: TestClient, case: str) -> None:
    got = send(client, case, NUL, NUL_PATH)
    assert got.status_code == 422, got.text

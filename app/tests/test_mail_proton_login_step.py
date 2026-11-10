"""How the app reads the keeper's answer to a login step (`ashley.mail.proton_login_http`): every refusal reason the keeper
names is carried through, an unknown one is `other`, and a human-check page is handed on only when it is an https page on
a proton.me host."""

from typing import Any, get_args, get_type_hints

import pytest
from ashley.mail import proton_login_http
from ashley.mail.proton_bridge import BridgeUnavailable
from ashley.mail.proton_login import Refused, Verify

step: Any = getattr(proton_login_http, "_step")


@pytest.mark.parametrize("reason", get_args(get_type_hints(Refused)["reason"]))
def test_each_reason_the_keeper_names_reaches_the_room(reason: str) -> None:
    got = step({"step": "refused", "reason": reason})
    assert isinstance(got, Refused) and got.reason == reason


def test_an_unknown_reason_is_other() -> None:
    assert step({"step": "refused", "reason": "brand-new"}) == Refused("other")
    assert step({"step": "refused"}) == Refused("other")


@pytest.mark.parametrize("url", ["https://verify.proton.me/?methods=captcha&token=t", "https://proton.me/x"])
def test_a_proton_page_is_handed_on(url: str) -> None:
    assert step({"step": "human_verification", "url": url}) == Verify(url)


@pytest.mark.parametrize("url", ["http://verify.proton.me/", "https://evil.example/?proton.me", "https://proton.me.evil.test/",
                                 "https://notproton.me/", "https://user@proton.me@evil.test/", "javascript:alert(1)", "",
                                 "https://x:y@proton.me/"])
def test_any_other_page_is_not(url: str) -> None:
    with pytest.raises(BridgeUnavailable):
        step({"step": "human_verification", "url": url})


def test_a_human_check_without_a_page_is_malformed() -> None:
    with pytest.raises(BridgeUnavailable):
        step({"step": "human_verification"})

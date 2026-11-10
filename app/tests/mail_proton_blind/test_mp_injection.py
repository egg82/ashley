"""A search value can narrow a search and never add to it or run a command (Gmail's `search_string` drops the characters
that mean something in its syntax; IMAP's quoting, parentheses, literals and line breaks are the same kind of syntax)."""

import pytest
from mail_proton_blind_store_support import compose, when
from mail_proton_blind_support import ALANA_ADDRESS, SEARCH, Box, World, data, stock

NOISE = ('nobody-9917" OR ALL', "nobody-9917) (ALL", "nobody-9917\r\nA1 DELETE INBOX", "nobody-9917 {5}\r\nALL  ", "nobody-9917 OR FROM pat",
         "nobody-9917\\\" NOT FROM zzz", "nobody-9917 UNSEEN", "nobody-9917 ) OR (", "nobody-9917 \x00")


@pytest.mark.parametrize("field", ["from", "to", "subject", "text", "label", "folder"])
@pytest.mark.parametrize("value", NOISE)
def test_a_value_with_search_syntax_in_it_does_not_widen_the_search_or_run_a_command(world: World, alana: Box, field: str, value: str) -> None:
    stock(alana)
    before = list(alana.account.commands)
    got = world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, **{field: value})
    if not got.is_error:
        assert data(got)["messages"] == []
    assert alana.account.commands == before
    assert "INBOX" in alana.account.folders and len(alana.account.present("INBOX")) == 3


def test_a_value_with_quotes_still_finds_what_it_names(world: World, alana: Box) -> None:
    alana.account.seed("INBOX", compose("Dinner at O'Neil's", "Pat <pat@school.test>", ALANA_ADDRESS, when(3, 2), "the \"special\" menu",
                                       message_id="<q@x.test>"))
    got = data(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, subject="Dinner"))["messages"]
    assert [m["subject"] for m in got] == ["Dinner at O'Neil's"]
    assert data(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, text="special"))["messages"]

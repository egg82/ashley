"""The settings log line's own fields carry key names and counts, never an entity id or a value."""

import logging

import pytest
from conn_settings_blind_support import connect_ha, write
from fastapi.testclient import TestClient
from test_cs_log import CHANGE, events


def test_no_field_of_the_changed_line_holds_an_id_or_a_value(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    cid = connect_ha(client)
    caplog.set_level(logging.INFO)
    write(client, cid, CHANGE)
    [line] = events(caplog, "connections.settings.changed")
    assert line, "the line carried no fields: the check below would pass on nothing"
    shown = repr(line)
    assert "household_reads" in shown
    assert "todo.inbox" not in shown and "switch.lamp" not in shown and "todo.get_items" not in shown

"""The stand-in leaves the process as it found it: uvicorn's loggers keep their level, propagation and handlers, so a
later test that reads log lines or a lifecycle line is not changed by it."""

from hag_server_support import LOGGERS_AT_IMPORT, logger_state
from hag_state_support import Ha


def test_starting_the_stand_in_leaves_uvicorn_s_loggers_as_found(ha: Ha) -> None:
    assert ha.url.startswith("http://127.0.0.1:")
    assert logger_state() == LOGGERS_AT_IMPORT

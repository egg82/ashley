"""The registry answers the Null kind for an unknown name, whose every read fails `unknown_kind`."""

import asyncio

from ashley.watches.kinds import Registry
from ashley.watches.model import ReadFailed
from ashley.watches.registry import KINDS
from watch_job_support import ScriptedKind, watch


def test_an_unknown_name_gets_the_null_kind() -> None:
    got = asyncio.run(Registry([ScriptedKind(name="a")]).get("b").read([watch(1), watch(2)]))
    assert got == {1: ReadFailed("unknown_kind"), 2: ReadFailed("unknown_kind")}


def test_a_known_name_gets_its_kind() -> None:
    kind = ScriptedKind(name="a")
    assert Registry([kind]).get("a") is kind


def test_the_app_has_the_claude_session_kind() -> None:
    assert KINDS.get("claude_session").name == "claude_session"

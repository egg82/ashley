"""The sort's wake starts a tainted turn that carries the watch's brief to her alone (design: "A watch gains `brief` (what
this watch's turn is for, as a reminder's brief is: people's data, never logged)"; "Its woken turn starts tainted")."""

from mail_sort_blind_support import BRIEF
from mail_sort_blind_turn_support import SORT_TOOLS, sort_watch, woken


def test_the_turn_a_sort_wakes_starts_tainted_by_the_watch() -> None:
    assert woken(sort_watch()).taint == "watch"
    assert woken(sort_watch()).taint == "watch"


def test_the_brief_reaches_her_in_the_note_and_is_never_stored_with_the_turn() -> None:
    inbound = woken(sort_watch())
    assert inbound.note is not None and BRIEF in inbound.note
    assert BRIEF not in inbound.text


def test_the_turn_offers_the_tools_the_watch_names() -> None:
    assert woken(sort_watch()).tools_only == SORT_TOOLS


def test_a_watch_with_no_brief_says_nothing_of_one() -> None:
    plain = woken(sort_watch(brief=None))
    assert plain.note is not None and "None" not in plain.note

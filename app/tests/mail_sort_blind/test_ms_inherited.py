"""A turn a tainted turn's reminder or watch fires starts tainted `inherited` through the real `Landing`: a label runs and a
move to the trash is held. Directed test added by the reconciler (not blind)."""

from dataclasses import replace

from mail_sort_blind_support import run
from mail_sort_blind_turn_support import M1, Rig, held, sort_watch, with_rig, woken


def test_an_inherited_turn_goes_by_the_tiers_from_its_first_call() -> None:
    async def body(rig: Rig) -> None:
        turn = rig.turn(replace(woken(sort_watch()), taint="inherited"))
        assert not held(await turn.label(M1, add=["School"]))
        assert held(await turn.label(M1, folder="trash"))
        assert len(turn.ran()) == 1

    run(with_rig(body))

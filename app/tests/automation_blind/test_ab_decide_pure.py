"""`decide` over a whole bench's commands, with no database: the Propose and Install rules judged against every effect
the bench holds, so a proposal of another piece is never taken for this piece's."""

from ab_support import body
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Add, Command, Install, Installed, Propose, Proposed
from ashley.workshop.decide import Accepted, Decision, replay
from ashley.workshop.model import HER, By, Text

RULES = workshop_rules.load()
ALANA = By(7)


def added(text: str | None = None) -> Add:
    return Add(ALANA, "automation", Text("porch", body() if text is None else text), "medium")


def outcomes(commands: list[Command]) -> list[str]:
    decisions: list[Decision] = replay(commands, RULES)
    return ["accepted" if isinstance(d, Accepted) else d.reason for d in decisions]


def test_an_install_naming_another_pieces_proposal_is_no_proposal() -> None:
    got = outcomes([added(), added(body(alias="b")), Propose(HER, 2, 1, True, None),
                    Install(ALANA, 1, 3, "ashley_bench_1_piece_1")])
    assert got == ["accepted", "accepted", "accepted", "no_proposal"]


def test_an_install_naming_its_own_proposal_carries_the_proposals_options() -> None:
    decisions = replay([added(), Propose(HER, 1, 1, True, "automation.old"),
                        Install(ALANA, 1, 2, "ashley_bench_1_piece_1")], RULES)
    last = decisions[-1]
    assert isinstance(last, Accepted)
    assert last.effect == Installed(1, 1, "ashley_bench_1_piece_1", True, "automation.old", 2)
    assert isinstance(decisions[1], Accepted) and decisions[1].effect == Proposed(1, 1, True, "automation.old")


def test_a_proposal_cannot_be_named_by_two_installs() -> None:
    install = Install(ALANA, 1, 2, "ashley_bench_1_piece_1")
    assert outcomes([added(), Propose(HER, 1, 1, False, None), install, install]) == [
        "accepted", "accepted", "accepted", "no_proposal"]


def test_her_install_is_needs_person_before_anything_else_is_judged() -> None:
    got = outcomes([added(), Propose(HER, 1, 1, False, None), Install(HER, 1, 2, "x"), Install(HER, 9, 99, "x")])
    assert got[2:] == ["needs_person", "needs_person"]

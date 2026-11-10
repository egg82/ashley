"""`ConnectionKinds.offered`: every kind for the first household and, for any other, every kind but the `deployment`
ones, in registration order; the first household is household 1."""

from ashley.connections.kinds import FIRST_HOUSEHOLD, ConnectionKinds
from hypothesis import given
from hypothesis import strategies as st
from pkb_support import deployment_kind

KINDS = (deployment_kind("plain1", deployment=False), deployment_kind("dep1"), deployment_kind("plain2", deployment=False),
         deployment_kind("dep2"))
REGISTRY = ConnectionKinds(KINDS)


def test_the_first_household_is_offered_every_kind() -> None:
    assert FIRST_HOUSEHOLD == 1
    assert REGISTRY.offered(FIRST_HOUSEHOLD) == KINDS


@given(st.integers(-5, 10**6).filter(lambda h: h != FIRST_HOUSEHOLD))
def test_any_other_household_is_offered_the_kinds_that_are_not_deployment_kinds_in_order(household: int) -> None:
    assert REGISTRY.offered(household) == (KINDS[0], KINDS[2])


def test_the_registry_still_lists_every_kind_to_everyone_who_asks_for_all() -> None:
    assert REGISTRY.all() == KINDS


def test_a_registry_of_only_deployment_kinds_offers_others_nothing() -> None:
    only = ConnectionKinds((deployment_kind("a"), deployment_kind("b")))
    assert only.offered(2) == () and len(only.offered(FIRST_HOUSEHOLD)) == 2

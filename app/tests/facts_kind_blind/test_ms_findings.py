"""Contract breaks the suite found, now fixed: an unhashable unit or source is refused, not raised."""

from typing import Any

import pytest
from ashley.workshop.facts import items_of, well_formed
from facts_kind_blind_support import body_of, decide_add, refused_as, with_

UNHASHABLE = [[], {}, [1], {"a": 1}]


@pytest.mark.parametrize("key", ["unit", "source"])
@pytest.mark.parametrize("junk", UNHASHABLE)
def test_a_list_or_object_as_unit_or_source_is_refused_not_raised(key: str, junk: Any) -> None:
    body = body_of([with_(**{key: junk})])
    assert well_formed(body) is False
    assert items_of(body) is None


@pytest.mark.parametrize("key", ["unit", "source"])
def test_decide_refuses_a_list_as_unit_or_source_as_bad_facts(key: str) -> None:
    assert refused_as(decide_add(body_of([with_(**{key: list[int]()})]))) == "bad_facts"

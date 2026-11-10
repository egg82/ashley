"""Who is talking, and who is home, for one message (`respond` step 1)."""

from dataclasses import dataclass

from .. import services
from ..people.model import Household, Person
from ..people.people import People
from ..senses.presence import Presence
from .model import Inbound


@dataclass(frozen=True)
class Who:
    """The household as read now, the speaker (None when unknown) and who is home (None when unknown)."""

    household: Household
    speaker: Person | None
    home: frozenset[int] | None


async def who(inbound: Inbound) -> Who:
    """The speaker is the channel's `speaker_id`, else the voice match's `heard_as`, else on a shared channel the one
    person home. Raises PeopleUnavailable; ValueError when the household is unknown or `speaker_id` or `heard_as`
    names someone not in it."""
    household = await services.get(People).household(inbound.household_id)
    if household is None:
        raise ValueError("no household has that id")
    home = await services.get(Presence).home(inbound.household_id)
    return Who(household, _speaker(inbound, household, home), home)


def _speaker(inbound: Inbound, household: Household, home: frozenset[int] | None) -> Person | None:
    people = {p.id: p for p in household.people}
    if inbound.speaker_id is not None:
        if inbound.speaker_id not in people:
            raise ValueError("the speaker is not in the household")
        return people[inbound.speaker_id]
    if inbound.heard_as is not None:
        if inbound.heard_as not in people:
            raise ValueError("the voice matched someone not in the household")
        return people[inbound.heard_as]
    if inbound.shared and home is not None and len(home) == 1:
        (only,) = home
        return people.get(only)
    return None

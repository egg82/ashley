"""The trust boundary of a continuous history, end to end: `respond` over real Postgres conversations, every other
system faked. A turn person A said where only A heard (their web login), and her answer to it, reach no prompt of a
reply someone else can hear: not the kitchen's with A and B present, whoever the voice names, and not B's own DM.
The same turns do reach A's next owner-only reply in another conversation, so the probe can see them."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from ashley import services
from ashley.channels.model import Audience, Inbound, Medium
from ashley.channels.respond import respond
from ashley.conversations.conversations import Conversations
from ashley.inference.inference import Inference
from ashley.inference.model import Message, Prompt
from ashley.inference.reply import Reply
from ashley.people.model import Household, Person
from ashley.people.people import People
from ashley.senses.presence import Presence
from ashley.tools.tools import Tools
from conversations_support import household, person, run, service
from turns_support import FakeInference, FakePeople, FakePresence, FakeTools

SECRET = "my therapist moved thursday's session"
HER_SECRET = "noted, therapy is on thursday now"
ASKED = "what is happening thursday"


@dataclass
class House:
    id: int
    alana: Person
    sam: Person
    presence: FakePresence
    inference: FakeInference


def _house(url: str) -> tuple[int, Person, Person]:
    home = household(url)
    return home, Person(person(url, home, "Alana"), home, "Alana"), Person(person(url, home, "Sam"), home, "Sam")


@asynccontextmanager
async def wired(url: str) -> AsyncGenerator[House]:
    home, alana, sam = _house(url)
    people, presence, inference = FakePeople(), FakePresence(), FakeInference()
    people.households = {home: Household(home, "home", "America/Denver", "", (alana, sam))}
    async with service(url) as conversations:
        for interface, impl in ((People, people), (Presence, presence), (Conversations, conversations),
                                (Tools, FakeTools()), (Inference, inference)):
            services.register(interface, impl)
        try:
            yield House(home, alana, sam, presence, inference)
        finally:
            for interface in (People, Presence, Conversations, Tools, Inference):
                services.unregister(interface)


def said(house: House, text: str, thread: str, audience: Audience, speaker: Person | None, medium: Medium = "text",
         heard_as: Person | None = None) -> Inbound:
    shared = audience != "owner"
    return Inbound(house.id, thread, text, "chat", medium, audience, None if speaker is None else speaker.id, shared,
                   "kitchen" if shared else None, "device" if shared else "web",
                   heard_as=None if heard_as is None else heard_as.id)


def everything(prompt: Prompt) -> str:
    """All the text the model was given: every system variant and every message."""
    return "\n".join([*(p.text for p in prompt.system.values()), *(m.text for m in prompt.messages if isinstance(m, Message))])


async def _alana_says_it_alone(house: House) -> None:
    house.inference.script = [Reply(spoken=HER_SECRET, text=HER_SECRET)]
    await respond(said(house, SECRET, f"web:{house.alana.id}", "owner", house.alana))


async def _heard(house: House, inbound: Inbound) -> str:
    house.inference.script = [Reply(spoken="Nothing I know of.", text="Nothing I know of.")]
    await respond(inbound)
    return everything(house.inference.asked[-1].prompt)


def test_a_private_web_turn_is_not_in_the_kitchens_prompt_with_both_home(db_url: str) -> None:
    async def scenario() -> None:
        async with wired(db_url) as house:
            await _alana_says_it_alone(house)
            house.presence.answer = frozenset({house.alana.id, house.sam.id})
            for heard_as in (None, house.alana, house.sam):
                text = await _heard(house, said(house, ASKED, "device:kitchen", "present", None, "spoken", heard_as))
                assert SECRET not in text and HER_SECRET not in text
                assert ASKED in text, "control: the prompt read is the kitchen's"

    run(scenario())


def test_a_private_web_turn_is_not_in_the_other_persons_dm(db_url: str) -> None:
    async def scenario() -> None:
        async with wired(db_url) as house:
            await _alana_says_it_alone(house)
            text = await _heard(house, said(house, ASKED, f"discord:dm:{house.sam.id}", "owner", house.sam))
            assert SECRET not in text and HER_SECRET not in text
            assert ASKED in text

    run(scenario())


def test_the_owner_alone_carries_it_into_another_conversation(db_url: str) -> None:
    async def scenario() -> None:
        async with wired(db_url) as house:
            await _alana_says_it_alone(house)
            text = await _heard(house, said(house, ASKED, f"discord:dm:{house.alana.id}", "owner", house.alana))
            assert SECRET in text and HER_SECRET in text

    run(scenario())


def test_a_reply_sent_only_to_a_shared_room_reaches_the_household(db_url: str) -> None:
    async def scenario() -> None:
        async with wired(db_url) as house:
            house.inference.script = [Reply(spoken="The boiler is serviced on friday.", text="Friday.")]
            await respond(said(house, "when is the boiler serviced", "device:kitchen", "present", house.alana, "spoken"))
            text = await _heard(house, said(house, "the boiler", f"discord:dm:{house.sam.id}", "owner", house.sam))
            assert "when is the boiler serviced" in text and "The boiler is serviced on friday." in text

    run(scenario())

"""The persona's account of the tools: `facts.tools` says what is out of reach, one sentence per unreachable source key;
`Context.tools_unreachable` reaches the system prompt and is filled by `respond` from `Catalogue.unreachable`; the
persona no longer says she cannot search the web. Her sources are the house and the look-up (`search`); the web and
places are the look-up's own and have no sentence of their own."""

from dataclasses import replace

import pytest
from ashley.channels.respond import respond
from ashley.persona import facts
from ashley.persona.persona import system
from ashley.tools.tools import Catalogue
from inference_support import settle
from test_contract_persona import CONTEXT
from turns_support import OTHER_SPEC, SPEC, World, inbound, world as world

HOUSE = facts.UNREACHABLE
SEARCH = "You can't look things up right now. Say so if asked."


def test_unreachable_tools_say_only_the_house_line_whatever_else_is_passed() -> None:
    assert facts.tools("zqINSTR", False) == "# Tools\n\n" + HOUSE
    assert facts.tools("zqINSTR", False, ("search",)) == "# Tools\n\n" + HOUSE


def test_reachable_tools_with_nothing_unreachable_are_the_stripped_instructions_or_nothing() -> None:
    assert facts.tools("  zqINSTR\n", True) == "# Tools\n\nzqINSTR"
    assert facts.tools("  \n", True) is None
    assert facts.tools(None, True) is None
    assert facts.tools(None, True, ()) is None


@pytest.mark.parametrize(("key", "sentence"), [("house", HOUSE), ("search", SEARCH)])
def test_one_unreachable_source_is_one_sentence(key: str, sentence: str) -> None:
    assert facts.tools(None, True, (key,)) == "# Tools\n\n" + sentence


def test_the_instructions_come_first_then_a_sentence_per_key_in_the_order_given() -> None:
    text = facts.tools("zqINSTR", True, ("search", "house"))
    assert text is not None and text.startswith("# Tools\n\nzqINSTR")
    assert text.index("zqINSTR") < text.index(SEARCH) < text.index(HOUSE)
    assert text.count(SEARCH) == text.count(HOUSE) == 1


def test_an_unknown_key_adds_no_sentence() -> None:
    assert facts.tools(None, True, ("zqKEY",)) is None
    assert facts.tools(None, True, ("web", "places")) is None
    assert facts.tools("zqINSTR", True, ("zqKEY",)) == "# Tools\n\nzqINSTR"
    assert facts.tools(None, True, ("zqKEY", "search")) == "# Tools\n\n" + SEARCH


def test_the_system_prompt_carries_the_unreachable_sentences_after_the_instructions() -> None:
    for text in (p.text for p in system("chat", replace(CONTEXT, tools_unreachable=("search",))).values()):
        assert "zqTOOLS use them well" in text and SEARCH in text and HOUSE not in text
        assert text.index("zqTOOLS") < text.index(SEARCH)


def test_nothing_unreachable_adds_no_sentence_to_the_system_prompt() -> None:
    for text in (p.text for p in system("chat", replace(CONTEXT, tools_unreachable=())).values()):
        assert SEARCH not in text and HOUSE not in text


def test_the_unreachable_keys_change_the_prompt() -> None:
    assert system("chat", replace(CONTEXT, tools_unreachable=("search",))) != system("chat", CONTEXT)


def test_she_no_longer_says_she_cannot_search_the_web() -> None:
    for text in (p.text for p in system("chat", CONTEXT).values()):
        assert "can't search the web" not in text.lower()


def test_respond_hands_the_persona_the_catalogues_unreachable_keys(world: World) -> None:
    world.tools.on_offer = Catalogue((SPEC, OTHER_SPEC), "use them", unreachable=("search",))
    settle(respond(inbound()))
    (_, context), = world.persona.asked
    assert context.tools_unreachable == ("search",) and context.tools_reachable is True


def test_respond_with_everything_reachable_hands_it_no_unreachable_keys(world: World) -> None:
    settle(respond(inbound()))
    assert world.persona.asked[0][1].tools_unreachable == ()

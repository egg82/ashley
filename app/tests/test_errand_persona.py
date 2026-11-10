"""The errand section of the persona: who asked, which source, the tools, and the time."""

from datetime import UTC, datetime

import pytest
from ashley.persona import errand
from contract.turns_support import ALANA, HOUSEHOLD

NOW = datetime(2026, 11, 6, 18, 30, tzinfo=UTC)


def test_the_prompt_names_the_asker_and_the_source_and_carries_the_tools() -> None:
    prompts = errand.system(HOUSEHOLD, ALANA, "house", "lights are lights", ("search",), NOW)
    prompt = prompts["default"]
    assert "# This errand" in prompt.stable and "Alana" in prompt.stable and "`house`" in prompt.stable
    assert "# Tools\n\nlights are lights" in prompt.stable
    assert "a dog named Pip" in prompt.stable
    assert "6:30 pm" in prompt.moment


def test_a_naive_time_is_refused() -> None:
    with pytest.raises(ValueError):
        errand.system(HOUSEHOLD, ALANA, "house", None, (), datetime(2026, 11, 6, 18, 30))

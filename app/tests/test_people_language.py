"""`people.language`: the language a locale names, and None wherever the household cannot say."""

import asyncio
from collections.abc import Generator

import pytest
from ashley.people.language import Language, language_for, language_of
from language_support import unwire, wire


@pytest.fixture(autouse=True)
def people_unwired() -> Generator[None]:
    yield
    unwire()


@pytest.mark.parametrize(("locale", "language"), [
    ("de-DE", Language("de", "German")), ("en-US", Language("en", "English")), ("en", Language("en", "English")),
    ("zh-Hans-CN", Language("zh", "Chinese")), ("es-419", Language("es", "Spanish")),
    ("pt-BR", Language("pt", "Portuguese")), ("xx-YY", None), ("fil-PH", None)])
def test_a_locale_names_its_language_by_the_subtag_before_the_first_dash(locale: str, language: Language | None) -> None:
    assert language_of(locale) == language


def test_a_household_speaks_the_language_of_its_locale() -> None:
    wire(1, "de-DE")
    assert asyncio.run(language_for(1)) == Language("de", "German")


def test_an_unknown_household_unwired_people_or_a_locale_without_a_language_keep_the_default() -> None:
    assert asyncio.run(language_for(1)) is None
    wire(1, "de-DE")
    assert asyncio.run(language_for(2)) is None
    wire(1, "xx-YY")
    assert asyncio.run(language_for(1)) is None

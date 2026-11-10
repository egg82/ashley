"""Pure parts of the Gmail adapter: a `MailQuery` as a `q` string that a value cannot add an operator to, and HTML as
text."""

from datetime import date

import pytest
from ashley.mail.body import html_text
from ashley.mail.gmail_query import search_string, words
from ashley.mail.model import MailQuery


def test_an_empty_query_asks_nothing() -> None:
    assert search_string(MailQuery()) == ""


def test_every_field_narrows() -> None:
    q = MailQuery(sender="a@b.test", to="c@d.test", subject="two words", text="lunch menu", after=date(2026, 1, 2),
                  before=date(2026, 3, 4), label="School", unread=False, has_attachment=False)
    assert search_string(q) == ('from:(a@b.test) to:(c@d.test) subject:(two words) lunch menu after:2026/01/02 '
                                'before:2026/03/04 label:"School" is:read -has:attachment')


@pytest.mark.parametrize("folder", ["inbox", "Sent", " DRAFTS ", "spam", "trash"])
def test_a_folder_is_an_in_search(folder: str) -> None:
    assert search_string(MailQuery(folder=folder)) == f"in:{folder.strip().lower()}"


def test_a_folder_that_is_none_of_the_five_is_a_label() -> None:
    assert search_string(MailQuery(folder="Receipts")) == 'label:"Receipts"'


@pytest.mark.parametrize("hostile", ["x in:trash", "from:boss", "(a OR b)", "-secret", 'a" label:"b', "{x} \\y"])
def test_a_value_cannot_add_an_operator(hostile: str) -> None:
    for query in (MailQuery(text=hostile), MailQuery(subject=hostile), MailQuery(sender=hostile), MailQuery(label=hostile)):
        q = search_string(query)
        assert ":" not in q.replace("subject:(", "").replace("from:(", "").replace("label:\"", "")
        assert "OR" not in q and " -" not in q and not q.startswith("-")


def test_words_drops_operators_and_what_is_left_empty() -> None:
    assert words("a OR b -c") == ["a", "b", "c"] and words('"" ()') == [] and words("OR") == []


def test_html_becomes_text_without_scripts_or_tags() -> None:
    assert html_text("<style>a{}</style><p>One</p><p>Two <i>three</i></p><script>bad()</script>") == "One\n\nTwo three"
    assert html_text("a&amp;b<br>c") == "a&b\nc"
    assert html_text("") == ""

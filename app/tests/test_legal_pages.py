"""`/privacy` and `/terms` are public HTML: no sign-in, never the client's index page, the privacy page carries
Google's Limited Use statement, which the OAuth consent screen depends on, and who runs the deployment comes from
settings, escaped, never from the tree."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ashley.settings import Settings
from ashley.web import legal


def client(**fields: str) -> TestClient:
    app = FastAPI()
    app.state.settings = Settings(database_url="", build_version="t", **fields)
    app.include_router(legal.router)
    return TestClient(app)


def test_both_pages_name_the_operator_settings_give_and_link_their_contact() -> None:
    made = client(public_url="https://ashley.test", operator_name="Sam <Doe> for the Doe household",
                  operator_contact="sam@doe.test")
    for path in ("/privacy", "/terms"):
        text = made.get(path).text
        assert "Sam &lt;Doe&gt; for the Doe household" in text and "<Doe>" not in text, path
        assert '<a href="mailto:sam@doe.test">sam@doe.test</a>' in text and "ashley.test" in text, path
        assert "$" not in text, path


def test_unset_the_pages_name_the_operator_generically_with_no_mail_link() -> None:
    for path in ("/privacy", "/terms"):
        text = client().get(path).text
        assert legal.NO_OPERATOR in text and legal.NO_CONTACT in text and "mailto:" not in text, path
        assert "this deployment ·" in text and "$" not in text, path


def test_the_privacy_page_is_public_html_with_the_limited_use_statement() -> None:
    page = client().get("/privacy")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "including the Limited Use requirements" in page.text
    assert "https://developers.google.com/terms/api-services-user-data-policy" in page.text


def test_the_terms_page_is_public_html() -> None:
    page = client().get("/terms")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "<h1>Terms</h1>" in page.text


def test_the_app_serves_both_pages_ahead_of_the_client() -> None:
    from ashley.main import create_app
    from ashley.settings import Settings

    app = create_app(Settings(database_url="", build_version="t", public_url="https://ashley.test"))
    whole = TestClient(app)
    for path in ("/privacy", "/terms"):
        page = whole.get(path)
        assert page.status_code == 200 and "<main>" in page.text, path

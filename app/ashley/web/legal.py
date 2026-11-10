"""The public privacy and terms pages, `/privacy` and `/terms`: HTML templates beside this module, served to anyone
without signing in, because Google's OAuth consent screen links to both. Who runs the deployment, how to reach them and
where it is served come from the app's settings (`operator_name`, `operator_contact`, `public_url`), never from the
tree."""

import html
from pathlib import Path
from string import Template
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

PAGES = Path(__file__).with_name("legal")
NO_OPERATOR = "the person who runs this deployment"
NO_CONTACT = "the person who invited you"

router = APIRouter(include_in_schema=False)


def render(name: str, public_url: str, operator_name: str, operator_contact: str) -> str:
    """`name` filled with these settings, each escaped; unset ones read as the deployment's operator."""
    host = urlsplit(public_url).hostname or "this deployment"
    contact = operator_contact.strip()
    reach = (f'<a href="mailto:{html.escape(contact, quote=True)}">{html.escape(contact)}</a>' if contact
             else html.escape(NO_CONTACT))
    return Template((PAGES / name).read_text(encoding="utf-8")).substitute(
        host=html.escape(host), operator=html.escape(operator_name.strip() or NO_OPERATOR), contact=reach)


@router.get("/privacy")
async def get_privacy(request: Request) -> HTMLResponse:
    return HTMLResponse(_page("privacy.html", request))


@router.get("/terms")
async def get_terms(request: Request) -> HTMLResponse:
    return HTMLResponse(_page("terms.html", request))


def _page(name: str, request: Request) -> str:
    settings = request.app.state.settings
    return render(name, settings.public_url, settings.operator_name, settings.operator_contact)

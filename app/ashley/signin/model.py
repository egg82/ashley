"""Sign-in as values."""

from dataclasses import dataclass

from ..people.model import Person


@dataclass(frozen=True)
class Pending:
    """A sign-in in flight, between sending the browser to the provider and its callback: the PKCE verifier, the nonce
    the ID token must carry, and the path on this site to return to."""

    verifier: str
    nonce: str
    next: str


@dataclass(frozen=True)
class LinkPending:
    """A link of a Discord account in flight, between sending the browser to Discord and its callback: the person who
    started it, whom alone it may link to, and the PKCE verifier."""

    household_id: int
    person_id: int
    verifier: str


@dataclass(frozen=True)
class Identity:
    """Who the provider says signed in: `sub`, its stable id for the account (a hashed user id), and `username`, its
    `preferred_username`, which may change and so names the account to the admin only, never to the code."""

    sub: str
    username: str


@dataclass(frozen=True)
class SignedIn:
    """A live session and the person it signs in."""

    session_id: int
    person: Person


@dataclass(frozen=True)
class Opened:
    """A session just opened: its cookie `token`, shown once and stored only hashed, and who it signs in."""

    token: str
    signed_in: SignedIn


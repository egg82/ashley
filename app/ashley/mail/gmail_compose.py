"""A `Draft` as the body Gmail's `users.drafts.create` and `users.messages.send` take
(https://developers.google.com/workspace/gmail/api/guides/sending): the message as RFC 2822 text in `raw`, base64url,
with `threadId` when it answers a message. Gmail sets `From` to the authenticated account."""

import base64

from . import compose
from .model import Draft


def raw_message(draft: Draft, replied_to: str = "", references: str = "") -> str:
    """`draft` as RFC 2822 text, base64url; `replied_to` and `references` are the `Message-ID` and `References` headers of
    the message it answers. Raises MailFailed `refused` for a header value that cannot be one (a line break in it)."""
    return base64.urlsafe_b64encode(compose.message(draft, replied_to, references).as_bytes()).decode()

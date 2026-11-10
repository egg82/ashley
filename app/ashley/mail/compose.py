"""A `Draft` as an RFC 2822 message, the part of writing mail no provider owns: the recipients, subject and text body,
and the threading headers of the message it answers. An adapter adds what its provider does not (Gmail sets `From`
itself; SMTP needs `From`, `Date` and `Message-ID`)."""

from email.message import EmailMessage
from email.policy import SMTP

from .model import Draft, MailFailed


def message(draft: Draft, replied_to: str = "", references: str = "") -> EmailMessage:
    """`draft` as a message; `replied_to` and `references` are the `Message-ID` and `References` headers of the message
    it answers. Raises MailFailed `refused` for a header value that cannot be one (a line break in it)."""
    built = EmailMessage(policy=SMTP)
    try:
        built["To"] = ", ".join(draft.to)
        if draft.cc:
            built["Cc"] = ", ".join(draft.cc)
        built["Subject"] = draft.subject
        if replied_to:
            built["In-Reply-To"] = replied_to
            built["References"] = f"{references} {replied_to}".strip()
        built.set_content(draft.body)
    except (ValueError, TypeError) as e:
        raise MailFailed("refused") from e
    return built

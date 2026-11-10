"""The recipient check of `mail_send` (`decisions.md`, "A turn that has read outside words asks before it does anything
consequential the person did not ask for"), made by code before the action judge is asked: who a message goes to is
identity, which code checks, never a reading of meaning. A recipient is known when it is the address of a mailbox the
household connected, one this mailbox has sent to before, or an address the person's own words contain. Any other
makes the call `recipient_unknown`, and no judge is asked.

The sent-to query is one `Mailbox.search` of the sent folder per recipient the cheaper checks did not settle. Logs
`outside.recipients` with the counts of recipients, household, named by the person and sent-before ones, and queries made,
never an address."""

import logging
import re
from collections.abc import Sequence

from .. import logs
from ..mail.mailbox import Mailbox
from ..mail.model import Account, Draft, MailFailed, MailQuery
from .action_judge import Vetting, View

log = logging.getLogger("ashley.tools")
_IN_WORDS = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
SENT = "sent"


def addresses_in(words: Sequence[str]) -> frozenset[str]:
    """The addresses the person's `words` contain, in lower case."""
    return frozenset(m.casefold() for w in words for m in _IN_WORDS.findall(w))


async def unknown(mailbox: Mailbox, account: Account, recipients: Sequence[str], household: frozenset[str],
                  words: Sequence[str]) -> tuple[str, ...]:
    """The `recipients` that are none of the `household`'s addresses, ones the person's `words` contain, or ones the
    `account`'s mailbox sent to before (a failed query counts as not known), in the order given."""
    said = addresses_in(words)
    lower = [r.casefold() for r in recipients]
    left = [r for r in lower if r not in household and r not in said]
    queries = 0
    strange: list[str] = []
    for address in dict.fromkeys(left):
        queries += 1
        if not await _sent_before(mailbox, account, address):
            strange.append(address)
    logs.info(log, "outside.recipients", recipients=len(lower), household=sum(1 for r in lower if r in household),
              said=sum(1 for r in lower if r in said and r not in household), queries=queries, unknown=len(strange))
    return tuple(r for r in lower if r in strange)


async def _sent_before(mailbox: Mailbox, account: Account, address: str) -> bool:
    try:
        page = await mailbox.search(account, MailQuery(to=address, folder=SENT))
    except MailFailed:
        return False
    return any(address in h.to.casefold() for h in page.items)


def vetting(draft: Draft, sender: str, strange: Sequence[str]) -> Vetting:
    """`recipient_unknown` as the reason when `strange` is not empty; else the view of the message: who it is from and
    to (every one a known address), and the subject and body as sizes."""
    if strange:
        return Vetting(ask="recipient_unknown")
    fields = {"from": sender, "to": ", ".join(draft.to), "subject": f"<text, {len(draft.subject)} chars>",
              "body": f"<text, {len(draft.body)} chars>"}
    if draft.cc:
        fields["cc"] = ", ".join(draft.cc)
    if draft.reply_to:
        fields["reply_to"] = "<a message of this mailbox>"
    return Vetting(view=View("mail_send", fields))

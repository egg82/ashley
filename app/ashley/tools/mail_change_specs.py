"""The specs of her three mail changes: a draft saved, a message sent, labels or folder or read state changed. Each is
`reads` false and `outside` false: it returns only a confirmation the code wrote. A change after mail has been read is held
for the person's OK by `ashley.tools.outside.Outside`."""

from ..inference.model import ToolSpec

DRAFT, LABEL, SEND = "mail_draft", "mail_label", "mail_send"
INSTRUCTIONS = ("mail_draft saves a message in the mailbox's drafts and mail_send sends one (plain addresses in `to` and "
                "`cc`; `reply_to` is the id of the message it answers). mail_label adds or removes the household's "
                "labels, moves messages to the inbox, archive, spam or trash, or marks them read or unread: name each "
                "message by its id with its `from` and `subject` as mail_search showed them, and the call is refused when "
                "they are not that message's. Once you have read mail, each of these waits for the person's OK instead of "
                "happening, and you say so.")


def specs(several: bool) -> tuple[ToolSpec, ...]:
    """The three change tools; `several` when the person has more than one mailbox that may be changed."""
    mailbox = {"mailbox": {"type": "string", "description": "The mailbox's address, as mail_boxes gives it"}}
    required = ["mailbox"] if several else []
    word, names = {"type": "string"}, {"type": "array", "items": {"type": "string"}}
    message = {"to": {"type": "array", "items": word, "description": "Plain addresses"}, "cc": names, "subject": word,
               "body": {"type": "string", "description": "The message's text"},
               "reply_to": {"type": "string", "description": "The id of the message this answers, when it does"}}
    written = {"type": "object", "properties": {**mailbox, **message}, "required": ["to", "body", *required]}
    entry = {"type": "object", "properties": {"id": word, "from": word, "subject": word}, "required": ["id", "from", "subject"]}
    labelled = {"mailbox": mailbox["mailbox"], "messages": {"type": "array", "items": entry},
                "add": {"type": "array", "items": word, "description": "Label names as mail_labels gives them"},
                "remove": names, "folder": {"type": "string", "description": "inbox, archive, spam or trash"},
                "unread": {"type": "boolean", "description": "true marks unread, false marks read"}}
    return (
        ToolSpec(DRAFT, "Save a message in a mailbox's drafts without sending it.", written, False, outside=False, tier="runs", label="Saved an email draft"),
        ToolSpec(LABEL, "Change the labels, folder or read state of listed messages of a mailbox.",
                 {"type": "object", "properties": labelled, "required": ["messages", *required]}, False, outside=False, tier="runs", label="Changed how an email is filed"),
        ToolSpec(SEND, "Send a message from a mailbox.", written, False, outside=False, tier="judged", label="Sent an email"))

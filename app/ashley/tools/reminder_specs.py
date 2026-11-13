"""What her reminder tools look like to the model (`reminders.ReminderTools`): structured fields only. `remind`'s
`for` is an enum of the household's names, so she can only name someone who is there."""

from collections.abc import Sequence

from ..inference.model import ToolSpec
from ..senses.deposit_rule import DIRECTIONS, MAX_NAME, PAYEE_MATCHES
from . import reminder_conditions as conditions
from ..senses.wakes import MAX_BRIEF
from .reminder_shape import DELIVERY, PROPERTIES, TOOLS

REMIND, LIST, CANCEL, ON_MONEY, ARM, CHANGE = ("remind", "reminders", "cancel_reminder", "remind_on_money",
                                               "arm_reminder", "change_reminder")
DEFAULT_TIME = "09:00"
"""When a reminder asked for a day and no time fires: the household's 09:00."""


def remind(names: Sequence[str], acting: bool = True) -> ToolSpec:
    """`acting` offers `tools`, the tools its turn may use when it falls due."""
    return ToolSpec(REMIND, "Set a reminder: at that time you will remind the person of it on their phone, once or "
                    "repeating, or do what they asked with the tools you name. Returns its id, or for one that acts "
                    "a proposal to tell them, which is not set until they agree.", {
                        "type": "object",
                        "properties": {
                            "for": {"type": "string", "enum": list(names),
                                    "description": "whom to remind: the speaker, or another person of the household"},
                            "at": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$",
                                   "description": "when, the household's local time, YYYY-MM-DDTHH:MM, or a date "
                                                  f"alone, YYYY-MM-DD, for {DEFAULT_TIME} that day; the first time "
                                                  "when it repeats"},
                            **PROPERTIES,
                            "what": {"type": "string", "maxLength": MAX_BRIEF,
                                     "description": "what to remind them of, or what to do, with any amounts and "
                                                    "names they need"},
                            "delivery": DELIVERY,
                            **({"tools": TOOLS} if acting else {}),
                        },
                        "required": ["for", "at", "what"],
                    }, outside=False, tier="runs", label="Set a reminder")


def _bare(prop: dict[str, object]) -> dict[str, object]:
    """A property without its description, for a spec whose fields mean what they do in `remind`."""
    return {k: v for k, v in prop.items() if k != "description"}


def change_reminder(acting: bool = True) -> ToolSpec:
    """Changing a reminder of theirs, by its id: only what is given changes."""
    return ToolSpec(CHANGE, "Change one of their reminders by its id, from reminders; it keeps its id and only what you "
                    "give changes, the fields being remind's. at moves its next time and starts a repeating one over "
                    "from there. Tools that act are a proposal to tell them, changing nothing until they agree.", {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "at": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$",
                                   "description": "its next time, the household's local time, YYYY-MM-DDTHH:MM, or a "
                                                  f"date alone for {DEFAULT_TIME}"},
                            **{k: _bare(v) for k, v in PROPERTIES.items()},
                            "what": {"type": "string", "maxLength": MAX_BRIEF},
                            "delivery": _bare(DELIVERY),
                            **({"tools": _bare(TOOLS)} if acting else {}),
                        },
                        "required": ["id"],
                    }, outside=False, tier="judged", label="Changed a reminder")


def remind_on_money(names: Sequence[str]) -> ToolSpec:
    return ToolSpec(ON_MONEY, "Propose a reminder that waits on money moving instead of a time (this arms nothing: it is armed only after the person answers, in a later message; call this in the message where you tell them the rule): each time a new deposit "
                    "into that account (direction in) or withdrawal from it (direction out) arrives, at least that "
                    "amount, with that payee, you will remind the person of it on their phone. A transfer between "
                    "their own accounts never counts. It needs a payee, a min_amount, conditions, or a mix; with none "
                    "it is refused. Conditions are general predicates you compose per ask (see conditions); code "
                    "judges them against the account's history. When it fires you are handed the transaction's "
                    "amount, day, payer and account, which conditions held, and the payer's history in the account, "
                    "as well as what you wrote. It stays set and fires on every match until it is cancelled. Returns "
                    "the rule in words.", {
                        "type": "object",
                        "properties": {
                            "for": {"type": "string", "enum": list(names),
                                    "description": "whom to remind: the speaker, or another person of the household"},
                            "direction": {"type": "string", "enum": list(DIRECTIONS),
                                          "description": "in for a deposit into the account, out for money leaving "
                                                         "it (a payment, a bill, a purchase)"},
                            "account_id": {"type": "string", "maxLength": MAX_NAME,
                                           "description": "the account the money moves in, by the id money_accounts "
                                                          "or a transaction there gives"},
                            "account": {"type": "string", "maxLength": MAX_NAME,
                                        "description": "that account's name as Sure shows it"},
                            "min_amount": {"type": "number", "exclusiveMinimum": 0,
                                           "description": "the smallest amount that counts, in the account's own "
                                                          "currency, as 1500 or 1500.50; give this or a payee"},
                            "payee": {"type": "string", "maxLength": MAX_NAME,
                                      "description": "the payee as Sure names it on a past transaction (its merchant or "
                                                     "transaction name), copied from what Sure shows; give this or "
                                                     "a min_amount"},
                            "conditions": conditions.schema(),
                            "judge": {"type": "boolean",
                                      "description": "true to decide yourself, when it lands, whether it is what they "
                                                     "meant: you are given the payer's history and may stay quiet "
                                                     "(`says` none) on a match that is not"},
                            "payee_match": {"type": "string", "enum": list(PAYEE_MATCHES),
                                            "description": "contains if the payee's name only has to include it "
                                                           "(the default), exact if it is the whole name"},
                            "what": {"type": "string", "maxLength": MAX_BRIEF,
                                     "description": "what to remind them of once it has happened; you are "
                                                    "also handed the transaction's own figures"},
                        },
                        "required": ["for", "direction", "account_id", "account", "what"],
                    }, outside=False, tier="runs", label="Set a reminder that waits on money moving")


ARM_SPEC = ToolSpec(ARM, "Agree the latest thing you proposed to this person in this conversation (a money rule with "
                    "remind_on_money, a reminder, a change or a watch that acts) once they have answered in a message that "
                    "came after the one you proposed it in. Refused in the same message as the proposal, or once it "
                    "has expired. Returns the reminder's id.",
                    {"type": "object", "properties": {}}, outside=False, agrees=True)
LIST_SPEC = ToolSpec(LIST, "List the reminders for the person you are talking with or set by them, soonest first.",
                     {"type": "object", "properties": {}}, reads=True, outside=False)
CANCEL_SPEC = ToolSpec(CANCEL, "Cancel one of their reminders by its id, from reminders; a repeating one stops for good.",
                       {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}, outside=False, tier="judged", label="Cancelled a reminder")

INSTRUCTIONS = ("When someone asks you to remind them, or another person of the household, of something at a time, "
                "set it with remind; times are the household's local time. Put everything they will need then in "
                "what, since you will see only that when it falls due.")
PRIVATE = (" You can list their reminders with reminders, change one with change_reminder (it keeps its id) and "
           "cancel one with cancel_reminder.")
ACTING = (" A reminder can do something instead of only telling them: name the tools it may use in tools, and say "
          "what to do in what. It is a proposal: tell them in one plain line what it will do, when and with which "
          "tools, and it is set only after they agree in a later message. Only tools you have now, for themselves.")
ARM_INSTRUCTIONS = (
    " You proposed something earlier in this conversation and they have answered since. Agree it with "
    "arm_reminder only if their message says yes to it as you last stated it. An answer to a question, a "
    "detail they supply (which account) or a change is not yes: say the rule again in one line and ask. Tell them it "
    "is set only once the call has succeeded. A yes is agreed by arm_reminder alone: proposing it again with remind, "
    "change_reminder or remind_on_money replaces your proposal and leaves nothing to agree.")
ON_MONEY_INSTRUCTIONS = (
    " When it is money they wait for, not a time, remind_on_money only proposes the rule; it arms nothing. Read what you "
    "need (money_accounts once, and one money_transactions search for past income, or expense for money leaving), "
    "call remind_on_money in this same message, and tell the person in one plain line which money would count and "
    "which would not (\"anything into your Bluebird checking that isn't your regular ACME paycheck or interest\"). It is "
    "not set until they agree: say it is a proposal and ask. Propose again if they change it. Use their words, not the "
    "tool's: never say min_amount, in, out, direction, conditions, judge, what or proposal. Never ask them which account "
    "when one read can tell you: take the account they named, and when their name for it matches no account's name, find "
    "it from the evidence (the account the regular income lands in) and put it in your line for them to confirm; never "
    "tell them it is not connected. You compose what counts. A payee or a minimum amount is the simple case; for money "
    "defined by being out of the ordinary (a bonus, a payout, a refund), use conditions measured against that payer's "
    "history in the account, never a guessed payee or amount: the payer's usual amounts and days come from the account, "
    "so a regular payer off its pattern is amount_vs_usual or day_vs_usual and a payer the account has not seen is "
    "payee_new. The regular payer can pay the bonus too, so its own deposit off its pattern is an alternative to "
    "include, not only a payer to leave out. Set judge when you would rather decide for yourself when it lands. Money "
    "leaving an account is the same with its direction out. Write what as what to tell them once it has happened.")

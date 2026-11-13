"""Her reply to a person, one field per medium. Pydantic is the one source: the type, its validator and the JSON
Schema every provider is sent."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..text import Cleaned

Says = Literal["reply", "offer", "none"]
"""Whether her reply is said (`reply`), is one short question offering to do something she overheard (`offer`), or is
not said at all (`none`). Code honours `offer` and `none` only where the turn offers them
(`ashley.channels.unprompted.says`)."""


def _all_required(schema: dict[str, Any]) -> None:
    """The schema a model is sent names every field required and carries no defaults, so it states each one; defaults
    are for callers. A default left in reaches the model as text in the field's description, and leans its answer."""
    schema["required"] = list(schema["properties"])
    for field in schema["properties"].values():
        field.pop("default", None)


class MemoryAct(BaseModel):
    """What she asks of her memory in one reply: `keep` what was just said, `correct` facts she holds, or `forget`
    them. `facts` are the ids from `What you remember` that a `correct` or `forget` is about; empty for `keep`."""

    model_config = ConfigDict(extra="forbid", frozen=True, json_schema_extra=_all_required)

    action: Literal["keep", "correct", "forget"] = Field(
        description="keep: remember or note something just said. correct: change a fact you hold. forget: erase a "
                    "fact you hold.")
    facts: tuple[int, ...] = Field(
        description="For correct and forget, the ids from `What you remember` of the facts it is about. Empty for "
                    "keep.")


class Reply(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, json_schema_extra=_all_required)

    answers: bool = Field(
        default=True, description="True when this reply is the answer itself. False when it would only say you are about "
                                  "to do something (look up, build, run, change) instead of having done it: you are "
                                  "then asked again and must do it.")
    # Never delivered or stored: it gives an offer somewhere to go that is not `spoken` or `text`.
    offer: Cleaned | None = Field(
        default=None, description="Anything you would add once the answer is done: an offer of more help or detail, "
                                  "the rest of something, or an invitation to ask more. Null when there is none. "
                                  "`spoken` and `text` end where the answer ends and never carry it.")
    spoken: Cleaned = Field(description="What she says aloud: plain sentences for a voice, no markup, lists or links. "
                                        "It ends where the answer ends; an offer of more goes in `offer`.")
    text: Cleaned = Field(description="What she writes in a chat: may use short Markdown and links. It ends where the "
                                      "answer ends; an offer of more goes in `offer`.")
    to_phone: bool = Field(
        default=False, description="True to send `text` to the speaker's phone, only when `# Now` says you can: for "
                                   "what doesn't work aloud, such as a link, a list or something long to keep, "
                                   "or on a turn you were woken for, what the person should have on their phone. "
                                   "Otherwise false.")
    aloud: bool = Field(
        default=False, description="True to have `spoken` played in your voice on the page the person spoke to you "
                                   "from, only when `# Now` says you can: when they are talking with you rather than "
                                   "reading, and the answer works heard. `text` is shown either way. Otherwise "
                                   "false.")
    memory: MemoryAct | None = Field(
        default=None, description="Set only when the person asks you to act on what you remember: to remember, note "
                                  "or keep something, to correct something you hold, or to forget or remove it. "
                                  "Also when they say it is worth keeping. It is then done at once, with what was "
                                  "said before it. Null when they only tell you something or ask for something else; "
                                  "what is said to you is kept anyway once the conversation goes quiet.")
    used_facts: tuple[int, ...] = Field(
        default=(), description="The ids of the remembered facts this reply relies on, from `What you remember`; "
                                "empty when it relies on none.")
    escalate: Cleaned | None = Field(
        default=None, description="Set only when this needs a stronger, slower mind than yours and you cannot answer "
                                  "it well yourself with your tools: a short line to the person in your own voice "
                                  "saying you will think it through and come back to them. It is said to them at "
                                  "once and the same question is then worked on by someone stronger; nothing else "
                                  "in this reply is used. Null for everything you can answer yourself, which is "
                                  "nearly everything.")
    owed: str | None = Field(
        default=None, description="Set only when you could not do what was just asked because a tool source is out of "
                                  "reach, and doing it later is still what they want, such as adding to a list or "
                                  "setting a reminder: the key of that source, `house` for the home and what is kept "
                                  "in it, `search` for looking things up. It is then done once the source answers and "
                                  "you tell them next time. Null for anything else: an ask the unreachable source "
                                  "does not bear on, one that only makes sense right now, a plain statement, "
                                  "or when every source answered.")
    says: Says = Field(
        default="reply", description="none only on a turn you were woken for (a wake from the house, or the person "
                                     "pausing on a bench; the message says which) when nothing in it is worth saying "
                                     "to them now, or when `# Now` says you may stay silent; then nothing you write is "
                                     "sent. offer only when `# Now` says you may offer: `spoken` and `text` are then one "
                                     "short question asking whether they want you to do it. reply on every other turn.")

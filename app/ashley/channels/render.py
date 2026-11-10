"""A reply as one medium delivers it."""

from .. import services
from ..inference.reply import Reply
from .lexicons import Lexicons
from .model import Medium


async def render(reply: Reply, medium: Medium, household_id: int | None) -> str:
    """`reply.spoken` with `household_id`'s pronunciation words applied for `spoken`, `reply.text` unchanged for `text`.
    The words apply only here, on the way out, so they never reach what is stored; no household has none."""
    said = delivered(reply, medium)
    if medium != "spoken":
        return said
    return (await services.get(Lexicons).of(household_id)).respell(said)


def delivered(reply: Reply, medium: Medium) -> str:
    """The field of `reply` that `medium` delivers, as stored: `render` before the words."""
    return reply.spoken if medium == "spoken" else reply.text

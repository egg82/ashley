"""Her Discord bot's token as a connection kind of the `chat` port. One bot serves the whole deployment, so it is a
`deployment` kind held by the first household, at Discord's one API address, and checked with the token by one read of
the bot's own user (`ashley.inference.key_check.answered`)."""

import httpx2

from ...connections.kinds import ConnectionKind, Refusal
from ...inference.key_check import answered

NAME = "discord"
API = "https://discord.com/api"


async def check(base: str, token: str, person_id: int) -> Refusal | None:
    """The bot's own user, read with `token`: None when Discord answers with it; `key_refused` when Discord turns the
    token away; `unreachable` for no answer in time or any other status."""
    async with httpx2.AsyncClient() as http:
        return await answered(http, base + "/v10/users/@me", {"Authorization": f"Bot {token}"})


KIND = ConnectionKind(
    name=NAME, title="Discord", what="her Discord bot",
    blurb="The deployment’s Discord bot token. She answers DMs and mentions as that bot while it is connected.",
    connected="Connected. She answers on Discord as this bot from now on.",
    removed="Removed. She is off Discord unless the deployment’s own setup has a token.",
    holders=frozenset({"household"}), schemes=frozenset({"https"}), address_placeholder="",
    secret_field="token", secret_label="Bot token, from the Discord developer portal", secret_noun="token",
    check=check, ports=frozenset({"chat"}), fixed_address=API, deployment=True,
    refusals={"bad_url": "Discord is reached at its own address",
              "key_refused": "Discord turned that token away; reset it in the developer portal and paste the new one",
              "unreachable": "Discord did not answer in time; try again shortly",
              "wrong_service": "what answered is not Discord’s API"})

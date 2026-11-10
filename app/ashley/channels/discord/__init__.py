"""The Discord channel adapter (`decisions.md`, "Discord is a bot, its Gateway a singleton"): one Gateway session held
by a singleton under the lease `discord` (`bot`), each message turned into an `Inbound` by `route` and claimed in
Postgres (`seen`) so exactly one process answers it, the reply split for Discord by `chunks`, what code shows beside it one more message (`receipts`). Only `client` touches the
library. Tunables are data, `discord.json`."""

from .receipts import receipt_lines as receipt_lines

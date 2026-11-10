"""Wire models for a code run shown under her reply (`api.chat_runs`)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ChatRunFile(BaseModel):
    """A text file a run left in its working directory."""

    name: str
    text: str


class ChatRun(BaseModel):
    """One script she ran for a message, as the page shows it under her answer. `result` is `ran` (then `exit_code`
    is the script's status, non-zero included), `timed_out` (stopped at its deadline; what it printed is kept),
    `out_of_memory`, `failed` (nothing readable came back) or `unknown` (the pod was made but what became of it could
    not be learned; the script may have run); it is null for a run with no recorded result (still going, or its runner
    stopped). `stdout` and `stderr` are empty until there is a result, and `cut` says one was cut to the sandbox's
    limit. `made` are the text files it left, `skipped` the names of those left out."""

    id: int
    language: Literal["python", "build123d"]
    script: str
    stdin: str
    started_at: datetime
    finished_at: datetime | None
    result: Literal["ran", "timed_out", "out_of_memory", "failed", "unknown"] | None
    exit_code: int | None
    stdout: str
    stderr: str
    cut: bool
    made: list[ChatRunFile]
    skipped: list[str]

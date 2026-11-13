"""Claude through the `claude` CLI on a subscription (`claude -p`), as a text provider for routes that offer no tools.

Each call runs the binary once, non-interactive: the history on stdin, the stable system prompt from a file (so neither
reaches the process list or an argument limit), the reply schema as `--json-schema`, no built-in tools, no settings,
MCP servers, skills or saved session. It runs in a directory of its own made for the call and removed after it, which
is also its `HOME` and `CLAUDE_CONFIG_DIR`, so nothing outlives the call on the node. Its environment is only `PATH`,
that directory and `CLAUDE_CODE_OAUTH_TOKEN`: none of this process's env (the database URL, `CONNECTIONS_KEY`, an API
key the CLI would prefer to the token) reaches it.

Params: `effort` (`low`, `medium`, `high`, `xhigh`, `max`), optional. The output is the CLI's one JSON result
(`--output-format json`); usage is its `modelUsage` summed over every model the call used. A result that is an error
fails by its `api_error_status` (`provider.status_failure`), an error with no status fails `error`, a stop of
`refusal` is a refusal, `max_tokens` is cut off, and a missing or invalid `structured_output` is `invalid_output`. A
binary that is absent or does not answer within the timeout fails `unavailable`. A failure message names the exit
code, the result's subtype and status; never the CLI's text, which can echo the prompt."""

import asyncio
import json
import os
import tempfile
from collections.abc import Mapping
from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError

from ..connections.kinds import Refusal
from . import anthropic_wire
from .model import MOMENT_LABEL, Entry, Message, SystemPrompt, ToolChoice, ToolSpec, Usage
from .provider import Completion, Provider, ProviderFailed, ProviderRefused, ToolUse, status_failure

T = TypeVar("T", bound=BaseModel)
_OBJECT = TypeAdapter(dict[str, Any])

NAME = "claude_cli"
"""The connection kind's name and the route name its provider is wired under."""
BINARY = "claude"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
CHECK_MODEL = "haiku"
"""The model a pasted token is checked with: the CLI's alias for its cheapest, so it never names a retired id."""
CHECK_TIMEOUT_S = 60.0
_FIXED = ("-p", "--output-format", "json", "--tools", "", "--setting-sources", "", "--strict-mcp-config",
          "--disable-slash-commands", "--no-session-persistence")


class _Check(BaseModel):
    ok: bool


class ClaudeCliProvider(Provider):
    """`name` is the route name; `token` the subscription's OAuth token (`claude setup-token`), kept out of `repr`;
    `binary` the executable, found on `PATH`."""

    def __init__(self, name: str, token: str, binary: str = BINARY) -> None:
        self._name = name
        self._token = token
        self._binary = binary

    def __repr__(self) -> str:
        return f"ClaudeCliProvider({self._name!r})"

    @property
    def name(self) -> str:
        return self._name

    @property
    def takes_tools(self) -> bool:
        return False

    def check_params(self, params: Mapping[str, object]) -> None:
        unknown = sorted(set(params) - {"effort"})
        if unknown:
            raise ValueError(f"unknown parameter {unknown[0]!r}")
        if "effort" in params and params["effort"] not in EFFORTS:
            raise ValueError(f"effort must be one of {', '.join(EFFORTS)}")

    async def complete(self, model: str, params: Mapping[str, object], system: SystemPrompt, messages: tuple[Entry, ...],
                       tools: tuple[ToolSpec, ...], tool_choice: ToolChoice, output: type[T],
                       timeout_s: float) -> Completion[T] | ToolUse:
        if tools:
            raise ProviderFailed("error", "the claude CLI provider is offered no tools")
        effort = params.get("effort")
        args = ["--model", model, "--json-schema", json.dumps(anthropic_wire.reply_schema(output))]
        args += ["--effort", effort] if isinstance(effort, str) else []
        result = await run(self._binary, self._token, args, system.stable, _transcript(system, messages), timeout_s)
        usage = _usage(result)
        if result.get("stop_reason") == "refusal":
            raise ProviderRefused("the model refused", usage)
        failure = _failure(result, usage)
        if failure is not None:
            raise failure
        try:
            return Completion(output.model_validate(result.get("structured_output")), usage or Usage(0, 0))
        except ValidationError as e:
            raise ProviderFailed("invalid_output", f"{type(e).__name__}: reply does not match the schema", usage) from e


async def check(base: str, key: str, person_id: int) -> Refusal | None:
    """The connection kind's check: one short call with `key` (`CHECK_MODEL`, `CHECK_TIMEOUT_S`). None when it answers;
    `key_refused` when the result is a 401 or 403; `unreachable` for anything else. Never raises."""
    try:
        result = await run(BINARY, key, ["--model", CHECK_MODEL, "--json-schema", json.dumps(_Check.model_json_schema())],
                           "Answer with ok set to true.", "Are you there?", CHECK_TIMEOUT_S)
    except ProviderFailed:
        return "unreachable"
    if result.get("api_error_status") in (401, 403):
        return "key_refused"
    return "unreachable" if result.get("is_error") is not False else None


async def run(binary: str, token: str, args: list[str], system: str, stdin: str, timeout_s: float) -> dict[str, Any]:
    """The CLI's JSON result for one non-interactive run (`_FIXED` plus `args`), `system` as its system prompt and
    `stdin` as the prompt, in a directory made for the run and removed after it. Raises ProviderFailed `unavailable`
    when the binary is absent or gives no result within `timeout_s` (it is killed), `error` when what it printed is not
    a JSON result."""
    with tempfile.TemporaryDirectory(prefix="claude-cli-") as home:
        prompt_file = os.path.join(home, "system.md")
        with open(prompt_file, "w") as f:
            f.write(system)
        env = {"PATH": os.environ.get("PATH", ""), "HOME": home, "CLAUDE_CONFIG_DIR": home,
               "CLAUDE_CODE_OAUTH_TOKEN": token}
        try:
            process = await asyncio.create_subprocess_exec(
                binary, *_FIXED, "--system-prompt-file", prompt_file, *args, cwd=home, env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        except OSError as e:
            raise ProviderFailed("unavailable", type(e).__name__) from e
        try:
            out, _ = await asyncio.wait_for(process.communicate(stdin.encode()), timeout_s)
        except TimeoutError as e:
            process.kill()
            await process.wait()
            raise ProviderFailed("unavailable", "TimeoutError") from e
    return _result(out, process.returncode)


def _result(out: bytes, code: int | None) -> dict[str, Any]:
    try:
        result = _object(json.loads(out))
    except ValueError:
        result = {}
    if result.get("type") != "result":
        raise ProviderFailed("error", f"claude exit={code} printed no JSON result")
    return {**result, "exit": code}


def _object(value: object) -> dict[str, Any]:
    """`value` as a JSON object, empty when it is not one."""
    try:
        return _OBJECT.validate_python(value)
    except ValidationError:
        return {}


def _transcript(system: SystemPrompt, messages: tuple[Entry, ...]) -> str:
    """The history as one prompt: each message under its author's label, oldest first, then the moment."""
    parts: list[str] = []
    for entry in messages:
        if not isinstance(entry, Message):
            raise ProviderFailed("error", "the claude CLI provider takes no tool history")
        parts.append(f"[{entry.author}]\n{entry.text}")
    if system.moment:
        parts.append(f"{MOMENT_LABEL}\n{system.moment}")
    return "\n\n".join(parts)


def _failure(result: Mapping[str, Any], usage: Usage | None) -> ProviderFailed | None:
    status, subtype = result.get("api_error_status"), result.get("subtype")
    reason = f"claude exit={result.get('exit')} subtype={subtype} status={status}"
    if result.get("is_error") is False and result.get("stop_reason") == "max_tokens":
        return ProviderFailed("invalid_output", "reply cut off at the token limit", usage, cut_off=True)
    if result.get("is_error") is False:
        return None
    if isinstance(status, int) and not isinstance(status, bool):
        return ProviderFailed(status_failure(status), reason, usage)
    if isinstance(subtype, str) and subtype.startswith("error_max_structured_output"):
        return ProviderFailed("invalid_output", reason, usage)
    return ProviderFailed("error", reason, usage)


def _usage(result: Mapping[str, Any]) -> Usage | None:
    """The tokens of every model the run used, from `modelUsage`; None when it reports none."""
    models = _object(result.get("modelUsage"))
    if not models:
        return None
    totals = [0, 0, 0, 0]
    for model in models.values():
        counts = _object(model)
        for i, key in enumerate(("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")):
            value = counts.get(key, 0)
            totals[i] += value if isinstance(value, int) and not isinstance(value, bool) else 0
    return Usage(*totals)

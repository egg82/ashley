"""The Claude subscription through the `claude` CLI (`ashley.inference.claude_cli`), against a fake `claude` on PATH that
records what it was run with and prints a result shaped as the real CLI's (`claude_cli_result.json`, one real
`--output-format json` result with its ids cut): the reply, the usage summed over every model, each failure kind, a
binary that is absent or hangs, the token check, and that it is never offered tools, at load or on a call."""

import asyncio
import copy
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from ashley.inference import anthropic_wire, claude_cli, kinds
from ashley.inference.claude_cli import ClaudeCliProvider
from ashley.inference.model import (MOMENT_LABEL, TOOLLESS, Message, Prompt, SystemPrompt, ToolSpec, Usage)
from ashley.inference.provider import Completion, ProviderFailed, ProviderRefused
from ashley.inference.router import RoutedInference
from ashley.inference.routes import TASKS, parse
from catalogue_support import NONE
from pydantic import BaseModel
from speech_support import MemoryLedger

REAL: dict[str, Any] = json.loads((Path(__file__).parent / "claude_cli_result.json").read_text())
FAKE = """#!{python}
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
prompt_file = args[args.index("--system-prompt-file") + 1] if "--system-prompt-file" in args else ""
record = {{"args": args, "stdin": sys.stdin.read(), "env": dict(os.environ), "cwd": os.getcwd(),
          "system": open(prompt_file).read() if prompt_file else None}}
json.dump(record, open(os.path.join(here, "record.json"), "w"))
time.sleep({sleep})
sys.stdout.write(open(os.path.join(here, "out.txt")).read())
sys.exit({code})
"""


class Answer(BaseModel):
    text: str


class Fake:
    """A `claude` on PATH printing `out` and exiting `code` after `sleep` seconds; `record` is what it was run with."""

    def __init__(self, where: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.where = where
        monkeypatch.setenv("PATH", f"{where}{os.pathsep}{os.environ.get('PATH', '')}")

    def answers(self, out: str | Mapping[str, Any], code: int = 0, sleep: float = 0) -> None:
        (self.where / "out.txt").write_text(out if isinstance(out, str) else json.dumps(out))
        script = self.where / "claude"
        script.write_text(FAKE.format(python=sys.executable, sleep=sleep, code=code))
        script.chmod(0o755)

    @property
    def record(self) -> dict[str, Any]:
        return json.loads((self.where / "record.json").read_text())

    @property
    def ran(self) -> bool:
        return (self.where / "record.json").exists()


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Fake:
    return Fake(tmp_path, monkeypatch)


def result(**fields: Any) -> dict[str, Any]:
    """The real result with `fields` replaced (None removes one)."""
    out = copy.deepcopy(REAL)
    for key, value in fields.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def error(status: int | None, subtype: str = "success") -> dict[str, Any]:
    return result(is_error=True, api_error_status=status, subtype=subtype, stop_reason="stop_sequence",
                  structured_output=None, result="the CLI's own words, which can echo the prompt")


SYSTEM = SystemPrompt("You decide what to remember.", "It is Tuesday morning.")
MESSAGES = (Message("person", "Sam: the bins go out on Thursdays"), Message("ashley", "Noted."),
            Message("person", "Sam: and recycling every other week"))


def complete(provider: ClaudeCliProvider, timeout_s: float = 10, tools: tuple[ToolSpec, ...] = (),
             params: Mapping[str, object] | None = None) -> Any:
    return asyncio.run(provider.complete("claude-sonnet-5-5", params or {"effort": "low"}, SYSTEM, MESSAGES, tools,
                                         "auto", Answer, timeout_s))


def test_a_reply_is_the_structured_output_with_the_usage_of_every_model(fake: Fake) -> None:
    models = copy.deepcopy(REAL["modelUsage"])
    models["claude-haiku-4-5-helper"] = {"inputTokens": 10, "outputTokens": 2, "cacheReadInputTokens": 3,
                                         "cacheCreationInputTokens": 4}
    fake.answers(result(structured_output={"text": "Bins on Thursdays."}, modelUsage=models))
    got = complete(ClaudeCliProvider("claude_cli", "oauth-token-1"))
    assert got == Completion(Answer(text="Bins on Thursdays."), Usage(1299 + 10, 145 + 2, 3, 4))


def test_the_run_gets_the_prompt_schema_and_token_and_nothing_of_this_process(
        fake: Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret@db/ashley")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-for-the-cli")
    fake.answers(REAL)
    complete(ClaudeCliProvider("claude_cli", "oauth-token-1"))
    seen = fake.record
    args = seen["args"]
    assert args[:2] == ["-p", "--output-format"] and args[2] == "json"
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--model") + 1] == "claude-sonnet-5-5"
    assert args[args.index("--effort") + 1] == "low"
    assert json.loads(args[args.index("--json-schema") + 1]) == anthropic_wire.reply_schema(Answer)
    assert {"--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands"} <= set(args)
    assert seen["system"] == SYSTEM.stable
    assert seen["stdin"] == ("[person]\nSam: the bins go out on Thursdays\n\n[ashley]\nNoted.\n\n"
                             "[person]\nSam: and recycling every other week\n\n" + MOMENT_LABEL + "\nIt is Tuesday morning.")
    assert set(seen["env"]) - {"PWD", "SHLVL", "_", "LC_CTYPE"} == {"PATH", "HOME", "CLAUDE_CONFIG_DIR",
                                                                   "CLAUDE_CODE_OAUTH_TOKEN"}
    assert seen["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth-token-1"
    assert seen["env"]["HOME"] == seen["env"]["CLAUDE_CONFIG_DIR"] == seen["cwd"]
    assert not os.path.exists(seen["cwd"]), "the run's directory outlived it"


def test_no_effort_param_sends_no_effort_flag(fake: Fake) -> None:
    fake.answers(REAL)
    asyncio.run(ClaudeCliProvider("claude_cli", "t").complete("m", {}, SYSTEM, MESSAGES, (), "auto", Answer, 10))
    assert "--effort" not in fake.record["args"]


@pytest.mark.parametrize(("printed", "failure"), [
    (error(401), "unavailable"), (error(429), "unavailable"), (error(529), "unavailable"), (error(400), "error"),
    (error(404), "error"), (error(None, "error_during_execution"), "error"),
    (error(None, "error_max_structured_output_retries"), "invalid_output"),
    (result(structured_output=None), "invalid_output"), (result(structured_output={"words": "x"}), "invalid_output"),
])
def test_each_result_fails_by_its_kind_and_never_quotes_the_cli(fake: Fake, printed: dict[str, Any],
                                                                 failure: str) -> None:
    fake.answers(printed, code=1 if printed.get("is_error") else 0)
    with pytest.raises(ProviderFailed) as caught:
        complete(ClaudeCliProvider("claude_cli", "t"))
    assert caught.value.failure == failure
    assert caught.value.usage == Usage(1299, 145)
    assert "echo the prompt" not in str(caught.value)


def test_a_refusal_is_final_and_a_reply_at_the_token_limit_is_cut_off(fake: Fake) -> None:
    fake.answers(result(stop_reason="refusal", structured_output=None))
    with pytest.raises(ProviderRefused) as refused:
        complete(ClaudeCliProvider("claude_cli", "t"))
    assert refused.value.usage == Usage(1299, 145)
    fake.answers(result(stop_reason="max_tokens", structured_output=None))
    with pytest.raises(ProviderFailed) as cut:
        complete(ClaudeCliProvider("claude_cli", "t"))
    assert (cut.value.failure, cut.value.cut_off) == ("invalid_output", True)


@pytest.mark.parametrize("printed", ["", "not json", json.dumps({"type": "assistant"}), json.dumps([1])])
def test_output_that_is_not_a_json_result_fails_error(fake: Fake, printed: str) -> None:
    fake.answers(printed, code=1)
    with pytest.raises(ProviderFailed) as caught:
        complete(ClaudeCliProvider("claude_cli", "t"))
    assert (caught.value.failure, caught.value.usage) == ("error", None)


def test_an_absent_binary_or_one_that_hangs_is_unavailable(fake: Fake) -> None:
    with pytest.raises(ProviderFailed) as absent:
        complete(ClaudeCliProvider("claude_cli", "t", binary="claude-not-installed"))
    assert absent.value.failure == "unavailable"
    fake.answers(REAL, sleep=30)
    with pytest.raises(ProviderFailed) as hung:
        complete(ClaudeCliProvider("claude_cli", "t"), timeout_s=0.3)
    assert (hung.value.failure, str(hung.value)) == ("unavailable", "TimeoutError")
    assert not os.path.exists(fake.record["cwd"])


def test_tools_offered_on_a_call_fail_without_running_it(fake: Fake) -> None:
    fake.answers(REAL)
    tool = ToolSpec("house_state", "Reads the house.", {"type": "object", "properties": {}})
    with pytest.raises(ProviderFailed) as caught:
        complete(ClaudeCliProvider("claude_cli", "t"), tools=(tool,))
    assert caught.value.failure == "error"
    assert not fake.ran


def test_params_are_checked() -> None:
    provider = ClaudeCliProvider("claude_cli", "t")
    provider.check_params({})
    provider.check_params({"effort": "max"})
    with pytest.raises(ValueError, match="effort"):
        provider.check_params({"effort": "huge"})
    with pytest.raises(ValueError, match="max_tokens"):
        provider.check_params({"max_tokens": 10})


def routes_with(task: str, entry: Mapping[str, object]) -> dict[str, object]:
    other = {"provider": "absent", "model": "m", "timeout_s": 5}
    return {"cooldown_s": 60, "tasks": {**{t: [other] for t in TASKS}, task: [entry]}}


CLI_ROUTE = {"provider": "claude_cli", "model": "claude-sonnet-5-5", "timeout_s": 30, "params": {"effort": "low"}}


def test_routes_name_it_only_for_a_task_that_offers_no_tools() -> None:
    checkers = {w.name: w for w in kinds.CLAUDE_CLI.build("placeholder").wired}
    for task in TOOLLESS:
        assert parse(routes_with(task, CLI_ROUTE), checkers).by_task[task][0].provider == "claude_cli"
    tool_tasks = [t for t in TASKS if t not in TOOLLESS]
    assert tool_tasks
    for task in tool_tasks:
        with pytest.raises(ValueError, match=f"{task}.*takes no tools"):
            parse(routes_with(task, CLI_ROUTE), checkers)


def test_a_step_offering_tools_for_a_toolless_task_is_refused_before_any_call(fake: Fake) -> None:
    fake.answers(REAL)
    checkers = {w.name: w for w in kinds.CLAUDE_CLI.build("t").wired}
    inference = RoutedInference(parse(routes_with("memory_judge", CLI_ROUTE), checkers), checkers.values(),
                                MemoryLedger(), NONE)
    tool = ToolSpec("house_state", "Reads the house.", {"type": "object", "properties": {}})
    with pytest.raises(ValueError, match="offers no tools"):
        asyncio.run(inference.step("memory_judge", Prompt({"default": SYSTEM}, MESSAGES[-1:], (tool,)), Answer))
    assert not fake.ran


def test_a_call_through_the_router_is_one_spend_row_with_its_tokens_and_no_guessed_cost(fake: Fake) -> None:
    fake.answers(result(structured_output={"text": "Bins on Thursdays."}))
    ledger = MemoryLedger()
    checkers = {w.name: w for w in kinds.CLAUDE_CLI.build("t").wired}
    inference = RoutedInference(parse(routes_with("memory_write", CLI_ROUTE), checkers), checkers.values(), ledger,
                                NONE)
    got = asyncio.run(inference.generate("memory_write", Prompt({"default": SYSTEM}, MESSAGES), Answer))
    assert got.text == "Bins on Thursdays."
    [call] = ledger.calls
    assert (call.task, call.provider, call.model, call.outcome) == ("memory_write", "claude_cli", "claude-sonnet-5-5",
                                                                    "ok")
    assert (call.usage, call.cost_usd) == (Usage(1299, 145), None)


def test_the_token_check_answers_refused_unreachable_or_none(fake: Fake) -> None:
    fake.answers(result(structured_output={"ok": True}))
    assert asyncio.run(claude_cli.check("https://api.anthropic.com", "good", 1)) is None
    assert fake.record["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "good"
    assert fake.record["args"][fake.record["args"].index("--model") + 1] == claude_cli.CHECK_MODEL
    for status, refusal in ((401, "key_refused"), (403, "key_refused"), (500, "unreachable")):
        fake.answers(error(status), code=1)
        assert asyncio.run(claude_cli.check("https://api.anthropic.com", "bad", 1)) == refusal
    fake.answers("garbage", code=1)
    assert asyncio.run(claude_cli.check("https://api.anthropic.com", "bad", 1)) == "unreachable"


def test_the_kind_is_the_deployments_and_its_token_is_kept_out_of_repr() -> None:
    kind = kinds.CLAUDE_CLI.kind
    assert (kind.name, kind.deployment, kind.secret_field, kind.ports) == ("claude_cli", True, "token",
                                                                           frozenset({"inference"}))
    assert kinds.CLAUDE_CLI in kinds.KEYED
    [provider] = kinds.CLAUDE_CLI.build("oauth-secret-value").wired
    assert "oauth-secret-value" not in repr(provider)

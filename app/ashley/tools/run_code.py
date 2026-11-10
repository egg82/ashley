"""Running a script for one turn (`channels.turn_tools`): one tool, `run_code`, offered while the locator's `Sandbox`
runs some language. Each call is one run: recorded in `Runs` before it starts and again with what came out, tied to the
person turn that asked, and run once in the sandbox. It is a change (its spec does not read), so the tool loop records
it as started before it runs and never runs it again on resume. Its result is the run's id, outcome, exit code,
output and the files it left."""

import time

from .. import services
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..runs import config as runs_config
from ..runs.config import RunsConfig
from ..runs.model import Job, Language, NewRun, Output
from ..runs.once import run_once
from ..runs.runs import RunsUnavailable
from ..runs.sandbox import Sandbox
from . import bench_results
from .bench_args import BadArguments, check_names
from .tools import Catalogue, Tools

NAME = "run_code"
CONFIG = runs_config.load()
LOOSE: tuple[Language, ...] = ("python",)
"""The languages a loose script may be in; the rest are run through a bench piece of their kind."""


def offered() -> tuple[Language, ...]:
    return tuple(lang for lang in services.get(Sandbox).languages() if lang in LOOSE)


def spec(languages: tuple[Language, ...], config: RunsConfig = CONFIG) -> ToolSpec:
    return ToolSpec(NAME, f"Run a short script once in a sandbox with no network and no access to the house, and get "
                    f"back what it printed, its exit code and the text files it left in its working directory. It "
                    f"is stopped after {config.languages["python"].script_timeout_s} seconds; only the standard library is there; nothing "
                    "is kept between runs.",
                    {"type": "object", "properties": {
                        "language": {"type": "string", "enum": list(languages)},
                        "script": {"type": "string", "description": f"the program, at most "
                                   f"{config.max_script_chars} characters"},
                        "stdin": {"type": "string", "description": "its standard input, if it reads one"}},
                     "required": ["language", "script"]}, outside=False, tier="runs")


INSTRUCTIONS = ("When a question needs exact arithmetic, a calculation over data, or checking that some code works, "
                "you can run a script with run_code instead of working it out in your head. Print what you need: "
                "you see only what it prints. Say what you ran when it matters to the answer.")


class RunCodeTools(Tools):
    def __init__(self, household_id: int, conversation_id: int, turn_id: int,
                 config: RunsConfig = CONFIG) -> None:
        self._household = household_id
        self._conversation = conversation_id
        self._turn = turn_id
        self._config = config

    async def catalogue(self) -> Catalogue:
        """Empty when the sandbox runs nothing."""
        languages = offered()
        return Catalogue((spec(languages, self._config),), INSTRUCTIONS) if languages else Catalogue((), None)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: bad arguments, a record that cannot be written, and a sandbox that cannot run it are each an
        error result, and nothing runs unless its start was recorded. A run whose output cannot be recorded still
        returns it, logged `runs.unrecorded`. Logs `tools.call` with the run id and outcome."""
        started = time.monotonic()
        if call.name != NAME:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            job = self._job(call)
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e))
        try:
            done = await run_once(NewRun(self._household, self._conversation, self._turn, call.id, job.language,
                                         job.script, job.stdin))
        except ValueError:
            return bench_results.failed(call, started, "bad_text", "a script or input may not hold a NUL character")
        except RunsUnavailable:
            return bench_results.failed(call, started, "unavailable", "code cannot be run right now; nothing ran")
        if not done.reached:
            return bench_results.failed(call, started, "unavailable", "the sandbox cannot run code right now",
                                        run=done.run_id)
        return bench_results.ok(call, started, result(done.run_id, done.output), run=done.run_id,
                                outcome_of_run=done.output.outcome)

    def _job(self, call: ToolCall) -> Job:
        check_names(call.arguments, spec(offered(), self._config))
        named, script = call.arguments.get("language"), call.arguments.get("script")
        stdin = call.arguments.get("stdin", "")
        languages = offered()
        if named not in languages:
            raise BadArguments("language is one the tool lists")
        language = languages[languages.index(named)]
        if not isinstance(script, str) or not script.strip() or len(script) > self._config.max_script_chars:
            raise BadArguments(f"script is a non-empty string of at most {self._config.max_script_chars} characters")
        if not isinstance(stdin, str) or len(stdin) > self._config.max_stdin_chars:
            raise BadArguments(f"stdin is a string of at most {self._config.max_stdin_chars} characters")
        return Job("", language, script, stdin)


LOST = ("the script was started but what it printed was lost, and whether it finished is not known: its output was "
        "lost, so do not take it as having done nothing")


def result(run_id: int, output: Output) -> dict[str, object]:
    """What she is told of a run; an `unknown` outcome carries a `note` saying its output was lost."""
    note = {"note": LOST} if output.outcome == "unknown" else {}
    return {**note, "run_id": run_id, "outcome": output.outcome, "exit_code": output.exit_code,
                       "stdout": output.stdout, "stderr": output.stderr, "output_cut": output.cut,
                       "files": dict(output.files), "files_left_out": list(output.skipped)}

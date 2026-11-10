"""The pod one job runs in: whatever the script, language, input or files say, the pod is the same locked-down pod, and
the job's values reach it only as environment values."""

import json
import re

import pytest
from dataclasses import replace
from typing import Any

from ashley.runs import runner
from ashley.runs.pod_spec import manifest
from hypothesis import given, settings
from hypothesis import strategies as st
from rcb_support import NAMESPACE, RUNTIME, check_isolated, container, decoded, job, skeleton
from sandbox_support import CONFIG, PYTHON

RUNNER = "print('runner')"
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
BASE = skeleton(manifest(job(), CONFIG, RUNNER, RUNTIME))
texts = st.text(max_size=300)
named_files = st.dictionaries(texts, texts, max_size=5)


def test_the_pod_is_isolated_by_every_property_of_the_contract() -> None:
    check_isolated(manifest(job(files={"a.txt": "x"}), CONFIG, RUNNER, RUNTIME), CONFIG)


def test_the_pod_is_named_for_the_job_in_the_sandbox_namespace() -> None:
    made = manifest(job("run-77"), CONFIG, RUNNER, RUNTIME)
    assert made["metadata"]["name"] == "run-77"
    assert made["metadata"].get("namespace", NAMESPACE) == NAMESPACE


def test_limits_and_deadline_follow_the_config() -> None:
    other = replace(CONFIG, languages={"python": replace(PYTHON, cpu="2", memory="64Mi", pod_deadline_s=99, work_mib=7)})
    made = manifest(job(), other, RUNNER, RUNTIME)
    check_isolated(made, other)
    sizes = {volume["emptyDir"]["sizeLimit"] for volume in made["spec"]["volumes"]}
    assert sizes == {"7Mi"}


def environ(made: dict[str, Any]) -> dict[str, str]:
    return {entry["name"]: entry["value"] for entry in container(made)["env"]}


def test_the_script_input_and_files_are_environment_values_and_nowhere_else() -> None:
    made = manifest(job(script="SCRIPT-ZQ", stdin="STDIN-ZQ", files={"NAME-ZQ.txt": "BODY-ZQ"}), CONFIG, RUNNER, RUNTIME)
    values = [decoded(entry) for entry in container(made)["env"] if entry["name"] != "ASHLEY_LIMITS"]
    for marker in ("SCRIPT-ZQ", "STDIN-ZQ", "BODY-ZQ", "NAME-ZQ.txt"):
        assert sum(marker in value for value in values) == 1, marker
    rest = json.dumps(skeleton(made))
    assert not any(marker in rest for marker in ("SCRIPT-ZQ", "STDIN-ZQ", "BODY-ZQ", "NAME-ZQ.txt"))


def test_each_value_is_its_own_variable_so_no_single_one_outgrows_the_cap() -> None:
    big = "x" * 90_000
    made = manifest(job(script=big, stdin=big + "y", files={"a": big, "b": big}), CONFIG, RUNNER, RUNTIME)
    env = container(made)["env"]
    assert max(len(entry["value"]) for entry in env) < 128 * 1024
    assert sum(big in decoded(entry) for entry in env if entry["name"] != "ASHLEY_LIMITS") >= 4


@pytest.mark.parametrize("text", ["$$", "$(X)", "$(HOME) $HOME ${HOME}", "$$(X)", "\\n %s {{x}}", "é\u2028\x00\r\n"])
def test_text_kubernetes_would_expand_reaches_the_container_unchanged(text: str) -> None:
    made = manifest(job(script=text, stdin=text, files={"f": text}), CONFIG, RUNNER, RUNTIME)
    assert runner.job(environ(made)) == (text, text, {"f": text})


@given(texts, texts, st.dictionaries(st.text(max_size=20).filter(lambda name: "\0" not in name), texts, max_size=5))
@settings(max_examples=100, deadline=None)
def test_arbitrary_text_arrives_intact_at_the_runner(script: str, stdin: str, files: dict[str, str]) -> None:
    made = manifest(job(script=script, stdin=stdin, files=files), CONFIG, RUNNER, RUNTIME)
    assert runner.job(environ(made)) == (script, stdin, files)


@given(texts, texts, named_files)
@settings(max_examples=60, deadline=None)
def test_nothing_in_the_script_input_or_files_changes_the_pod(script: str, stdin: str, files: dict[str, str]) -> None:
    made = manifest(job(script=script, stdin=stdin, files=files), CONFIG, RUNNER, RUNTIME)
    assert skeleton(made) == BASE
    check_isolated(made, CONFIG)


@given(texts, texts, named_files)
@settings(max_examples=60, deadline=None)
def test_the_environment_names_are_never_chosen_by_the_job(script: str, stdin: str, files: dict[str, str]) -> None:
    env: list[dict[str, Any]] = container(manifest(job(script=script, stdin=stdin, files=files), CONFIG, RUNNER, RUNTIME))["env"]
    names = [entry["name"] for entry in env]
    assert len(names) == len(set(names))
    assert all(NAME.match(name) and name.startswith("ASHLEY_") for name in names)
    assert len(names) <= 3 + len(files)


@given(texts, st.text(alphabet=st.characters(codec="ascii", exclude_characters='"\\'), max_size=40))
@settings(max_examples=40, deadline=None)
def test_a_hostile_script_cannot_widen_what_the_pod_may_touch(script: str, name_part: str) -> None:
    hostile = "\n".join([script, "hostPath: /", "privileged: true", "automountServiceAccountToken: true", name_part])
    made = manifest(job(script=hostile, stdin=hostile, files={hostile: hostile}), CONFIG, RUNNER, RUNTIME)
    check_isolated(made, CONFIG)
    assert skeleton(made) == BASE

"""The job reaches the runner unchanged whatever its text: Kubernetes expands `$(NAME)` and `$$` in an env value, so
each value goes in base64, which has no `$`, and `runner.job` decodes it back to exactly what was recorded."""

from hypothesis import given, settings, strategies as st

from ashley.runs import runner
from ashley.runs.model import Job
from ashley.runs.pod_spec import manifest
from sandbox_support import CONFIG

TEXT = st.text(st.characters(blacklist_characters="\x00", blacklist_categories=("Cs",)), max_size=200)
NAMES = st.text(st.characters(blacklist_characters="\x00/", blacklist_categories=("Cs",)), min_size=1, max_size=20)


def env_of(job: Job) -> dict[str, str]:
    env = manifest(job, CONFIG, "")["spec"]["containers"][0]["env"]
    return {e["name"]: e["value"] for e in env}


@settings(max_examples=60, deadline=None)
@given(TEXT, TEXT, st.dictionaries(NAMES, TEXT, max_size=3))
def test_any_text_reaches_the_runner_unchanged(script: str, stdin: str, files: dict[str, str]) -> None:
    env = env_of(Job("run-1", "python", script, stdin, files))
    assert not any("$" in v for k, v in env.items() if k != "ASHLEY_LIMITS")
    assert runner.job(env) == (script, stdin, files)


def test_kubernetes_references_in_the_text_are_not_expanded() -> None:
    script, stdin = "print('$$ and $(HOME)')", "$(ASHLEY_SCRIPT)"
    env = env_of(Job("run-1", "python", script, stdin))
    assert runner.job(env) == (script, stdin, {})

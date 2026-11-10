"""The Kubernetes sandbox against a fake API (`sandbox_support.FakeKube`): the pod it asks for has no network, no token,
no host mounts, gVisor, limits and a deadline; the job goes in through the pod spec alone; the output comes from the
log, checked and cut again; and the pod is deleted however the run ends."""

import asyncio
from pathlib import Path
from typing import Any

import httpx2
import pytest
from ashley import logs
from ashley.runs import runner
from ashley.runs.kube_api import KubeApi
from ashley.runs.kubernetes import RUNNER, KubernetesSandbox
from ashley.runs.model import Job, Output
from ashley.runs.sandbox import SandboxUnavailable
from sandbox_support import CONFIG, PYTHON, Clock, FakeKube, Script, envelope_line

SECRET = "print('plans-for-the-shed')"
JOB = Job("run-7", "python", SECRET, stdin="the input", files={"data.csv": "a,b\n1,2\n"})


def sandbox(fake: FakeKube, clock: Clock | None = None) -> KubernetesSandbox:
    clock = clock or Clock()
    return KubernetesSandbox(fake.api(), CONFIG, sleep=clock.sleep, clock=clock)


def ran(fake: FakeKube, job: Job = JOB) -> Output:
    return asyncio.run(sandbox(fake).run(job))


def spec_of(fake: FakeKube) -> dict[str, Any]:
    assert len(fake.created) == 1
    return fake.created[0]["spec"]


def container(fake: FakeKube) -> dict[str, Any]:
    containers = spec_of(fake)["containers"]
    assert len(containers) == 1
    return containers[0]


@pytest.fixture
def fake(tmp_path: Path) -> FakeKube:
    return FakeKube(tmp_path / "token")


# --- the pod's security properties (red first) ---

def test_the_pod_runs_under_gvisor_in_the_sandbox_namespace(fake: FakeKube) -> None:
    ran(fake)
    assert spec_of(fake)["runtimeClassName"] == "gvisor"
    assert fake.created[0]["metadata"]["namespace"] == "ashley-sandbox"


def test_the_pod_gets_no_token_no_host_network_no_service_links_and_no_cluster_dns(fake: FakeKube) -> None:
    ran(fake)
    spec = spec_of(fake)
    assert spec["automountServiceAccountToken"] is False
    assert spec["hostNetwork"] is False and spec["hostPID"] is False and spec["hostIPC"] is False
    assert spec["enableServiceLinks"] is False
    assert spec["dnsPolicy"] == "None"
    assert spec["dnsConfig"] == {"nameservers": ["127.0.0.1"]}


def test_the_pod_has_a_deadline_never_restarts_and_has_limits(fake: FakeKube) -> None:
    ran(fake)
    spec = spec_of(fake)
    assert spec["activeDeadlineSeconds"] == PYTHON.pod_deadline_s
    assert spec["restartPolicy"] == "Never"
    resources = container(fake)["resources"]
    assert resources["limits"] == {"cpu": PYTHON.cpu, "memory": PYTHON.memory}
    assert resources["requests"] == {"cpu": PYTHON.cpu_request, "memory": PYTHON.memory}


def test_the_pod_mounts_only_its_own_size_limited_empty_dirs(fake: FakeKube) -> None:
    ran(fake)
    volumes = spec_of(fake)["volumes"]
    assert volumes and all(set(v) == {"name", "emptyDir"} for v in volumes)
    assert all(v["emptyDir"]["sizeLimit"] == f"{PYTHON.work_mib}Mi" for v in volumes)


def test_the_container_is_locked_down_and_runs_the_pinned_image(fake: FakeKube) -> None:
    ran(fake)
    c = container(fake)
    assert c["image"] == PYTHON.image
    sc = c["securityContext"]
    assert sc["runAsNonRoot"] is True and isinstance(sc["runAsUser"], int) and sc["runAsUser"] > 0
    assert sc["allowPrivilegeEscalation"] is False and sc["readOnlyRootFilesystem"] is True
    assert sc["capabilities"] == {"drop": ["ALL"]}
    assert sc["seccompProfile"] == {"type": "RuntimeDefault"}


def test_the_job_goes_in_through_the_spec_alone(fake: FakeKube) -> None:
    ran(fake)
    c = container(fake)
    env = {e["name"]: e["value"] for e in c["env"]}
    assert runner.job(env) == (SECRET, "the input", {"data.csv": "a,b\n1,2\n"})
    assert c["command"] == ["python", "-I", "-B", "-c", RUNNER]


# --- the pod is always deleted ---

@pytest.mark.parametrize("script", [
    Script(),
    Script(log=envelope_line(1, stderr="Traceback")),
    Script(phases=["Running", "Failed"], log="", reason="DeadlineExceeded"),
    Script(phases=["Running", "Failed"], log="", terminated="OOMKilled"),
    Script(log_status=500),
])
def test_the_pod_is_deleted_whatever_the_script_did(fake: FakeKube, script: Script) -> None:
    fake.script = script
    ran(fake)
    assert fake.deleted == ["run-7"] and not fake.pods


def test_an_api_that_stays_down_mid_run_gives_an_unknown_outcome_and_the_pod_is_deleted(fake: FakeKube) -> None:
    fake.fail = lambda r: 500 if r.method == "GET" and r.url.path.endswith("/run-7") else None
    assert ran(fake) == Output("unknown", None, "", "")
    assert fake.deleted == ["run-7"]


def test_a_transient_poll_error_is_retried(fake: FakeKube) -> None:
    failed: list[str] = []

    def once(r: httpx2.Request) -> int | None:
        if r.method == "GET" and r.url.path.endswith("/run-7") and not failed:
            failed.append("x")
            return 503
        return None

    fake.fail = once
    assert ran(fake).outcome == "ran"
    assert failed


def test_a_log_that_cannot_be_read_after_the_run_gives_an_unknown_outcome(fake: FakeKube) -> None:
    fake.script = Script(log_status=500)
    assert ran(fake).outcome == "unknown"


def test_a_pod_that_never_starts_is_unavailable_and_deleted(fake: FakeKube) -> None:
    fake.script = Script(phases=["Pending"])
    with pytest.raises(SandboxUnavailable):
        ran(fake)
    assert fake.deleted == ["run-7"]


def test_a_refused_pod_is_unavailable(fake: FakeKube) -> None:
    fake.fail = lambda r: 403 if r.method == "POST" else None
    with pytest.raises(SandboxUnavailable):
        ran(fake)
    assert not fake.created and not fake.pods


def test_the_api_unreachable_is_unavailable(tmp_path: Path) -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down")

    token = tmp_path / "token"
    token.write_text("t")
    api = KubeApi(httpx2.AsyncClient(base_url="https://kube.test", transport=httpx2.MockTransport(down)), str(token))
    with pytest.raises(SandboxUnavailable):
        asyncio.run(KubernetesSandbox(api, CONFIG, sleep=Clock().sleep, clock=Clock()).run(JOB))


# --- what comes back ---

def test_output_comes_from_the_log_marked_line(fake: FakeKube) -> None:
    fake.script = Script(log="noise\n" + envelope_line(3, stdout="42\n", stderr="warn", files={"out.txt": "x"}))
    assert ran(fake) == Output("ran", 3, "42\n", "warn", False, {"out.txt": "x"}, ())


def test_a_forged_oversized_line_is_cut_to_the_limits(fake: FakeKube) -> None:
    files = {"a": "1", "b": "2", "c": "3", "big": "x" * 100}
    fake.script = Script(log=envelope_line(0, stdout="y" * 500, files=files))
    out = ran(fake)
    assert len(out.stdout) == CONFIG.output_chars and out.cut
    assert len(out.files) == CONFIG.max_files and set(out.skipped) | set(out.files) == set(files)


def test_a_timed_out_script_keeps_what_it_printed(fake: FakeKube) -> None:
    fake.script = Script(log=envelope_line(None, stdout="partial", timed_out=True))
    assert ran(fake) == Output("timed_out", None, "partial", "")


def test_without_a_marked_line_the_pod_status_says_what_happened(fake: FakeKube) -> None:
    fake.script = Script(phases=["Failed"], log="", reason="DeadlineExceeded")
    assert ran(fake).outcome == "timed_out"
    fake2 = FakeKube(fake.token_file.with_name("t2"), Script(phases=["Failed"], log="Killed", terminated="OOMKilled"))
    assert ran(fake2).outcome == "out_of_memory"
    fake3 = FakeKube(fake.token_file.with_name("t3"), Script(phases=["Failed"], log="garbage"))
    assert ran(fake3) == Output("failed", None, "", "")


def test_a_malformed_line_is_failed_not_trusted(fake: FakeKube) -> None:
    fake.script = Script(log=envelope_line(0).replace('"exit_code": 0', '"exit_code": "0"'))
    assert ran(fake).outcome == "failed"


# --- housekeeping ---

def test_pods_left_by_a_stopped_app_pod_are_swept_and_young_ones_kept(fake: FakeKube) -> None:
    fake.leftover("run-1", "2000-01-01T00:00:00Z")
    fake.leftover("run-2", "2999-01-01T00:00:00Z")
    ran(fake)
    assert "run-1" in fake.deleted and "run-2" in fake.pods


def test_the_token_is_read_from_its_file_on_every_call(fake: FakeKube) -> None:
    box = sandbox(fake)

    async def twice() -> None:
        await box.run(JOB)
        fake.token_file.write_text("token-two\n")
        await box.run(Job("run-8", "python", "1"))

    asyncio.run(twice())
    assert fake.tokens[0] == "Bearer token-one" and fake.tokens[-1] == "Bearer token-two"


def test_logs_carry_the_pod_and_outcome_never_the_script_or_output(fake: FakeKube,
                                                                   capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    fake.script = Script(log=envelope_line(0, stdout="plans-for-the-shed"))
    ran(fake)
    out = capsys.readouterr().out
    assert "event=runs.sandbox" in out and "pod=run-7" in out and "outcome=ran" in out
    assert "plans-for-the-shed" not in out and "the input" not in out

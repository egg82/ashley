"""The pod one job runs in, as the Kubernetes API takes it: gVisor (`runtime_class`), no service account token, no host
namespaces, no service environment, no resolver, never restarted, CPU and memory limits, `activeDeadlineSeconds`, a
locked-down non-root container on the language's pinned image with a read-only root, and two size-limited emptyDirs (`/work`, the
script's working directory, and `/out`, where its output streams go). The job is in the container's environment, one
variable per value, each base64 (`runner`). A job with binary inputs also gets a third emptyDir, `inputs`, filled before
the script starts by an init container (`unpack`), which reads a tar of them from its standard input, pushed by the app
through the Kubernetes API (`KubernetesSandbox`), and mounted read-only at `/work/inputs` in the run container. So no pod has a network. No host path,
ConfigMap or Secret is mounted. The namespace denies all traffic."""

import base64
import json
from typing import Any

from .config import Profile, RunsConfig
from .labels import PREFIX
from .model import Job

LABEL = PREFIX + "run"
NOBODY = 65534
INIT = "unpack"
MIB = 1024 * 1024


def manifest(job: Job, config: RunsConfig, runner: str, runtime_class: str, unpacker: str = "") -> dict[str, Any]:
    """`runner` is the program the container runs (`runner.py`'s text), `runtime_class` the pod's RuntimeClass. A job
    with inputs also needs `unpacker`, the init container's program (`unpack.py`'s text). Raises ValueError for a
    language the config does not run."""
    profile = config.profile(job.language)
    if profile is None:
        raise ValueError(f"{job.language} is not run")
    volumes: list[dict[str, Any]] = [{"name": name, "emptyDir": {"sizeLimit": f"{profile.work_mib}Mi"}}
                                     for name in ("work", "out")]
    spec: dict[str, Any] = {
        "runtimeClassName": runtime_class,
        "automountServiceAccountToken": False,
        "hostNetwork": False, "hostPID": False, "hostIPC": False,
        "enableServiceLinks": False,
        "dnsPolicy": "None", "dnsConfig": {"nameservers": ["127.0.0.1"]},
        "restartPolicy": "Never",
        "activeDeadlineSeconds": profile.pod_deadline_s,
        "terminationGracePeriodSeconds": 0,
        "securityContext": {"runAsNonRoot": True, "runAsUser": NOBODY, "runAsGroup": NOBODY,
                            "fsGroup": NOBODY, "seccompProfile": {"type": "RuntimeDefault"}},
        "containers": [_container(job, config, profile, runner)],
        "volumes": volumes}
    if job.inputs:
        volumes.append({"name": "inputs", "emptyDir": {"sizeLimit": _quantity(profile.input_bytes)}})
        spec["initContainers"] = [_unpack_container(job, profile, unpacker)]
        spec["containers"][0]["volumeMounts"].append({"name": "inputs", "mountPath": "/work/inputs", "readOnly": True})
    return {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": job.name, "labels": {LABEL: "true"}}, "spec": spec}


def _quantity(size: int) -> str:
    return f"{-(-size // MIB)}Mi"


def _unpack_container(job: Job, profile: Profile, unpacker: str) -> dict[str, Any]:
    task = {"files": [{"name": name, "size": file.size, "sha256": file.sha256} for name, file in sorted(job.inputs.items())]}
    return {"name": INIT, "image": profile.image, "imagePullPolicy": "IfNotPresent",
            "command": ["python", "-I", "-B", "-c", unpacker],
            "stdin": True, "stdinOnce": True,
            "env": [{"name": "ASHLEY_INPUTS", "value": _b64(json.dumps(task))}],
            "resources": {"requests": {"cpu": "50m", "memory": "64Mi"}, "limits": {"cpu": "250m", "memory": "128Mi"}},
            "securityContext": {"runAsNonRoot": True, "runAsUser": NOBODY, "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]},
                                "seccompProfile": {"type": "RuntimeDefault"}},
            "volumeMounts": [{"name": "inputs", "mountPath": "/inputs"}]}


def _container(job: Job, config: RunsConfig, profile: Profile, runner: str) -> dict[str, Any]:
    limits = {"cpu": profile.cpu, "memory": profile.memory}
    requests = {"cpu": profile.cpu_request, "memory": profile.memory}
    return {"name": "run", "image": profile.image, "imagePullPolicy": "IfNotPresent",
            "command": ["python", "-I", "-B", "-c", runner],
            "workingDir": "/work",
            "env": _env(job, config, profile),
            "resources": {"requests": requests, "limits": limits},
            "securityContext": {"runAsNonRoot": True, "runAsUser": NOBODY, "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]},
                                "seccompProfile": {"type": "RuntimeDefault"}},
            "volumeMounts": [{"name": "work", "mountPath": "/work"}, {"name": "out", "mountPath": "/out"}]}


def _env(job: Job, config: RunsConfig, profile: Profile) -> list[dict[str, str]]:
    limits = {"timeout_s": profile.script_timeout_s, "output_chars": config.output_chars,
              "file_chars": config.file_chars, "max_files": config.max_files, "log_bytes": profile.log_bytes}
    if profile.artifact_bytes:
        limits["artifact_bytes"] = profile.artifact_bytes
    env = [{"name": "ASHLEY_SCRIPT", "value": _b64(job.script)}, {"name": "ASHLEY_STDIN", "value": _b64(job.stdin)},
           {"name": "ASHLEY_LIMITS", "value": json.dumps(limits)}]
    env += [{"name": f"ASHLEY_FILE_{i}", "value": _b64(f"{name}\0{text}")}
            for i, (name, text) in enumerate(sorted(job.files.items()))]
    return env


def _b64(text: str) -> str:
    """Base64 of the UTF-8, which has no `$` for Kubernetes to expand."""
    return base64.b64encode(text.encode("utf-8")).decode("ascii")

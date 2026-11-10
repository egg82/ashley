"""The pod one job runs in, as the Kubernetes API takes it: gVisor (`runtime_class`), no service account token, no host
namespaces, no service environment, no resolver, never restarted, CPU and memory limits, `activeDeadlineSeconds`, a
locked-down non-root container on the language's pinned image with a read-only root, and two size-limited emptyDirs (`/work`, the
script's working directory, and `/out`, where its output streams go). The job is in the container's environment, one
variable per value, each base64 (`runner`); binary inputs ride the same way, deflated and cut in chunks. No host path, ConfigMap or Secret is mounted. The namespace denies all traffic."""

import base64
import json
import zlib
from collections.abc import Mapping
from typing import Any

from .config import Profile, RunsConfig
from .labels import PREFIX
from .model import Job

LABEL = PREFIX + "run"
NOBODY = 65534


def manifest(job: Job, config: RunsConfig, runner: str, runtime_class: str) -> dict[str, Any]:
    """`runner` is the program the container runs (`runner.py`'s text), `runtime_class` the pod's RuntimeClass. Raises ValueError for a language the config
    does not run."""
    profile = config.profile(job.language)
    if profile is None:
        raise ValueError(f"{job.language} is not run")
    return {"apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": job.name, "labels": {LABEL: "true"}},
            "spec": {
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
                "volumes": [{"name": name, "emptyDir": {"sizeLimit": f"{profile.work_mib}Mi"}} for name in ("work", "out")],
            }}


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
    return env + _blobs(job.inputs)


BLOB_CHUNK = 100_000
"""Characters of base64 in one variable; Linux caps a single environment string at 128 KiB."""


def _blobs(inputs: Mapping[str, bytes]) -> list[dict[str, str]]:
    env: list[dict[str, str]] = []
    for i, (name, data) in enumerate(sorted(inputs.items())):
        packed = base64.b64encode(zlib.compress(data)).decode("ascii")
        env.append({"name": f"ASHLEY_BLOBNAME_{i:03d}", "value": _b64(name)})
        env += [{"name": f"ASHLEY_BLOB_{i:03d}_{k:04d}", "value": packed[at:at + BLOB_CHUNK]}
                for k, at in enumerate(range(0, len(packed), BLOB_CHUNK))]
    return env


def _b64(text: str) -> str:
    """Base64 of the UTF-8, which has no `$` for Kubernetes to expand."""
    return base64.b64encode(text.encode("utf-8")).decode("ascii")

"""The pod one media job runs in, as the Kubernetes API takes it: the pinned media image on gVisor, no service account
token, never restarted, a deadline, CPU and memory limits, a locked-down non-root container with a read-only root and
its scratch (`/work`, which holds the file) in a size-limited emptyDir, with an ephemeral-storage request and limit that
cover it and the log. It resolves names and reaches the app (to fetch the file) and the speech service, as the
namespace's network policy (the cluster repo) allows pods carrying `LABEL`; only a pod carrying `FETCH_LABEL`
also reaches public HTTPS. The file's link is in the container's
environment and nowhere else."""

import json
from typing import Any

from .labels import PREFIX
from .media_config import MediaConfig

LABEL = PREFIX + "media"
FETCH_LABEL = PREFIX + "fetch"
NOBODY = 65534


def manifest(name: str, url: str, task: dict[str, Any], deadline_s: int, config: MediaConfig, image: str,
             runtime_class: str, runner: str, fetch: bool = False) -> dict[str, Any]:
    """`task` is the runner's JSON task, `image` the pinned media image, `runtime_class` the RuntimeClass, `runner` the
    program the container runs (`media_runner.py`'s text). `fetch` marks a pod that reaches public HTTPS (a YouTube
    captions job) with `FETCH_LABEL`, which no other media pod carries."""
    return {"apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": name, "labels": {LABEL: "true", **({FETCH_LABEL: "true"} if fetch else {})}},
            "spec": {
                "runtimeClassName": runtime_class,
                "automountServiceAccountToken": False,
                "hostNetwork": False, "hostPID": False, "hostIPC": False,
                "enableServiceLinks": False,
                "restartPolicy": "Never",
                "activeDeadlineSeconds": deadline_s,
                "terminationGracePeriodSeconds": 0,
                "securityContext": {"runAsNonRoot": True, "runAsUser": NOBODY, "runAsGroup": NOBODY,
                                    "fsGroup": NOBODY, "seccompProfile": {"type": "RuntimeDefault"}},
                "containers": [_container(url, task, config, image, runner)],
                "volumes": [{"name": "work", "emptyDir": {"sizeLimit": f"{config.work_mib}Mi"}}],
            }}


def _container(url: str, task: dict[str, Any], config: MediaConfig, image: str, runner: str) -> dict[str, Any]:
    limits = {"cell_width": config.cell_width, "single_width": config.single_width, "qualities": list(config.qualities),
              "max_bytes": config.max_sheet_bytes, "silence_peak": config.silence_peak,
              "speech_timeout_s": config.speech_timeout_s, "fetch_timeout_s": config.fetch_timeout_s,
              "captions_timeout_s": config.captions_timeout_s}
    storage = f"{config.ephemeral_mib}Mi"
    return {"name": "media", "image": image, "imagePullPolicy": "IfNotPresent",
            "command": ["python", "-I", "-B", "-c", runner],
            "workingDir": "/work",
            "env": [{"name": "ASHLEY_MEDIA_URL", "value": url}, {"name": "ASHLEY_MEDIA_TASK", "value": json.dumps(task)},
                    {"name": "ASHLEY_MEDIA_LIMITS", "value": json.dumps(limits)},
                    {"name": "HOME", "value": "/work"}, {"name": "TMPDIR", "value": "/work"}],
            "resources": {"requests": {"cpu": config.cpu_request, "memory": config.memory, "ephemeral-storage": storage},
                          "limits": {"cpu": config.cpu, "memory": config.memory, "ephemeral-storage": storage}},
            "securityContext": {"runAsNonRoot": True, "runAsUser": NOBODY, "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]},
                                "seccompProfile": {"type": "RuntimeDefault"}},
            "volumeMounts": [{"name": "work", "mountPath": "/work"}]}

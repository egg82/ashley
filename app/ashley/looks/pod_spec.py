"""The pod one look runs in, as the Kubernetes API takes it: a browser in the pinned image on gVisor, no service account
token, never restarted, with a deadline, CPU and memory limits, a locked-down non-root container with a read-only root,
a memory-backed `/dev/shm` for Chromium, and its scratch (`HOME`, `TMPDIR`: the root is read-only and Playwright
makes its temporary directories before it launches) in the size-limited `/home/look`, with an ephemeral-storage
request and limit that cover it and the log. Unlike a code run's pod it resolves names, to reach the app's page; what
it may reach is the namespace's network policy (the cluster repo), which the label `LABEL` selects. The page's address
is in the container's environment and nowhere else.

The warm pod (`warm_manifest`) is the same pod kept up: it serves looks (`shooter.serve`) instead of taking one page,
restarts if its container dies, has no deadline (the keeper recycles it), and is Ready once it answers `/healthz`; the
Service `WARM_SERVICE` selects it by `WARM_LABEL`, and it carries `LABEL` too so the same network policy lets it reach
the app.

A read pod (`read_manifest`) is a look pod given a public page instead of the app's: it carries `FETCH_LABEL` too, so
the same policy that lets the captions fetch reach public HTTPS (and nothing private) lets it reach the page."""

import json
from typing import Any

from ..runs.labels import PREFIX
from ..runs.media_pod import FETCH_LABEL
from .config import LooksConfig
from .shooter import PORT

LABEL = PREFIX + "look"
WARM_LABEL = PREFIX + "look-warm"
WARM_SERVICE = "ashley-look-warm"
NOBODY = 65534


def manifest(name: str, url: str, config: LooksConfig, image: str, runtime_class: str, shooter: str) -> dict[str, Any]:
    """`image` is the pinned browser image, `runtime_class` the RuntimeClass, `shooter` the program the container
    runs (`shooter.py`'s text)."""
    env = {"ASHLEY_LOOK_URL": url, "ASHLEY_LOOK_LIMITS": json.dumps(_limits(config))}
    spec = {"restartPolicy": "Never", "activeDeadlineSeconds": config.pod_deadline_s}
    return _pod(name, {LABEL: "true"}, spec, _container(env, config, image, shooter), config, runtime_class)


def read_manifest(name: str, url: str, config: LooksConfig, image: str, runtime_class: str,
                  shooter: str) -> dict[str, Any]:
    """A pod that reads one public page (`shooter.read`): a look pod that also carries the media fetch pod's
    `FETCH_LABEL`, which the namespace's policy lets reach public HTTPS and nothing private."""
    limits = {"ready_s": config.ready_timeout_s, "read_bytes": config.read_bytes}
    env = {"ASHLEY_LOOK_MODE": "read", "ASHLEY_LOOK_URL": url, "ASHLEY_LOOK_LIMITS": json.dumps(limits)}
    spec = {"restartPolicy": "Never", "activeDeadlineSeconds": config.pod_deadline_s}
    return _pod(name, {LABEL: "true", FETCH_LABEL: "true"}, spec, _container(env, config, image, shooter), config,
                runtime_class)


def warm_manifest(name: str, prefix: str, config: LooksConfig, image: str, runtime_class: str,
                  shooter: str) -> dict[str, Any]:
    """The warm pod; `prefix` is where it may open pages (the app's look page path)."""
    env = {"ASHLEY_LOOK_MODE": "serve", "ASHLEY_LOOK_LIMITS": json.dumps(_limits(config)),
           "ASHLEY_LOOK_PREFIX": prefix, "ASHLEY_LOOK_WAIT_S": str(config.pod_deadline_s)}
    container = _container(env, config, image, shooter)
    container["ports"] = [{"containerPort": PORT}]
    container["readinessProbe"] = {"httpGet": {"path": "/healthz", "port": PORT}, "periodSeconds": 5}
    return _pod(name, {LABEL: "true", WARM_LABEL: "true"}, {"restartPolicy": "Always"}, container, config, runtime_class)


def _pod(name: str, labels: dict[str, str], lifecycle: dict[str, Any], container: dict[str, Any], config: LooksConfig,
         runtime_class: str) -> dict[str, Any]:
    return {"apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": name, "labels": labels},
            "spec": {
                "runtimeClassName": runtime_class,
                "automountServiceAccountToken": False,
                "hostNetwork": False, "hostPID": False, "hostIPC": False,
                "enableServiceLinks": False,
                **lifecycle,
                "terminationGracePeriodSeconds": 0,
                "securityContext": {"runAsNonRoot": True, "runAsUser": NOBODY, "runAsGroup": NOBODY,
                                    "fsGroup": NOBODY, "seccompProfile": {"type": "RuntimeDefault"}},
                "containers": [container],
                "volumes": [{"name": "shm", "emptyDir": {"medium": "Memory", "sizeLimit": f"{config.shm_mib}Mi"}},
                            {"name": "home", "emptyDir": {"sizeLimit": f"{config.home_mib}Mi"}}],
            }}


def _limits(config: LooksConfig) -> dict[str, int]:
    return {"width": config.width, "height": config.height, "max_height": config.max_height,
            "quality": config.jpeg_quality, "max_bytes": config.max_image_bytes, "ready_s": config.ready_timeout_s}


def _container(env: dict[str, str], config: LooksConfig, image: str, shooter: str) -> dict[str, Any]:
    storage = f"{config.ephemeral_mib}Mi"
    env = {**env, "HOME": "/home/look", "TMPDIR": "/home/look"}
    return {"name": "look", "image": image, "imagePullPolicy": "IfNotPresent",
            "command": ["python", "-I", "-B", "-c", shooter],
            "workingDir": "/home/look",
            "env": [{"name": k, "value": v} for k, v in env.items()],
            "resources": {"requests": {"cpu": config.cpu_request, "memory": config.memory, "ephemeral-storage": storage},
                          "limits": {"cpu": config.cpu, "memory": config.memory, "ephemeral-storage": storage}},
            "securityContext": {"runAsNonRoot": True, "runAsUser": NOBODY, "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]},
                                "seccompProfile": {"type": "RuntimeDefault"}},
            "volumeMounts": [{"name": "shm", "mountPath": "/dev/shm"}, {"name": "home", "mountPath": "/home/look"}]}

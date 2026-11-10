"""The Proton Bridge pod and its token Secret, as the Kubernetes API takes them. One pod per epoch, named for it
(`pod_name`), running the pinned `apps/ashley-mail-bridge` image, whose entry point is the keeper
(`deploy/mail-bridge/keeper.py`). The keeper reads its environment:

- `ASHLEY_URL`: where the pod reaches the app, `BRIDGE_EPOCH`, `BRIDGE_TOKEN` (from the Secret, never in the pod spec),
  `BRIDGE_HEARTBEAT_S`, `BRIDGE_FENCE_S`;
- `BRIDGE_TLS_DIR`: the directory the pod's Secret mounts its control-port certificate and key in (`proton_tls`);
- `BRIDGE_CONTROL_PORT`, `BRIDGE_IMAP_PORT`, `BRIDGE_SMTP_PORT`: the pod's ports for the app's control calls and for the
  relays to Bridge's own loopback IMAP and SMTP.

Bridge's cache is an `emptyDir` of `cache_mib`, never shipped; so is the home that holds the vault and keychain. A pod
carries `LABEL`, which the cluster repo's Service and network policy select on."""

from typing import Any

from . import proton_tls
from .config import MailConfig

LABEL = "ashley.yggdrasil.pub/mail-bridge"
EPOCH_LABEL = "ashley.yggdrasil.pub/mail-bridge-epoch"
CONTROL_PORT = 8080
IMAP_PORT = 2143
SMTP_PORT = 2025
USER = 1000
TOKEN_KEY = "token"
TLS_DIR = "/etc/keeper-tls"


def pod_name(epoch: int) -> str:
    return f"mail-bridge-{epoch}"


def secret_labels(epoch: int) -> dict[str, str]:
    return {LABEL: "true", EPOCH_LABEL: str(epoch)}


def manifest(epoch: int, image: str, app_url: str, config: MailConfig) -> dict[str, Any]:
    """The pod for `epoch`: non-root, a read-only root, never restarted (the singleton makes the next under a new epoch),
    its token read from the Secret of the same name."""
    name = pod_name(epoch)
    env = [{"name": "ASHLEY_URL", "value": app_url}, {"name": "BRIDGE_EPOCH", "value": str(epoch)},
           {"name": "BRIDGE_HEARTBEAT_S", "value": str(config.heartbeat_s)},
           {"name": "BRIDGE_FENCE_S", "value": str(config.fence_s)},
           {"name": "BRIDGE_CONTROL_PORT", "value": str(CONTROL_PORT)},
           {"name": "BRIDGE_IMAP_PORT", "value": str(IMAP_PORT)}, {"name": "BRIDGE_SMTP_PORT", "value": str(SMTP_PORT)},
           {"name": "HOME", "value": "/home/bridge"}, {"name": "BRIDGE_TLS_DIR", "value": TLS_DIR},
           {"name": "BRIDGE_TOKEN", "valueFrom": {"secretKeyRef": {"name": name, "key": TOKEN_KEY}}}]
    container = {
        "name": "bridge", "image": image, "imagePullPolicy": "IfNotPresent", "env": env,
        "ports": [{"name": "control", "containerPort": CONTROL_PORT}, {"name": "imap", "containerPort": IMAP_PORT},
                  {"name": "smtp", "containerPort": SMTP_PORT}],
        "securityContext": {"runAsNonRoot": True, "runAsUser": USER, "allowPrivilegeEscalation": False,
                            "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]},
                            "seccompProfile": {"type": "RuntimeDefault"}},
        "volumeMounts": [{"name": "home", "mountPath": "/home/bridge"}, {"name": "tmp", "mountPath": "/tmp"},
                         {"name": "tls", "mountPath": TLS_DIR, "readOnly": True}]}
    return {"apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": name, "labels": secret_labels(epoch)},
            "spec": {"restartPolicy": "Never", "enableServiceLinks": False, "terminationGracePeriodSeconds": 5,
                     "securityContext": {"runAsNonRoot": True, "runAsUser": USER, "runAsGroup": USER,
                                         "fsGroup": USER},
                     "containers": [container],
                     "volumes": [{"name": "home", "emptyDir": {"sizeLimit": f"{config.cache_mib}Mi"}},
                                 {"name": "tmp", "emptyDir": {"sizeLimit": "64Mi"}},
                                 {"name": "tls", "secret": {"secretName": name, "defaultMode": 0o440,
                                                            "items": [{"key": proton_tls.CERT_KEY, "path": "tls.crt"},
                                                                      {"key": proton_tls.KEY_KEY, "path": "tls.key"}]}}]}}

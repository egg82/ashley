"""`pod_spec.warm_manifest`: the look pod kept up. It has the look pod's locked-down spec, serves looks instead of
taking one page (no page address in it), restarts if its container dies, has no deadline, is Ready once it answers
`/healthz`, carries `WARM_LABEL` (which `WARM_SERVICE` selects) and `LABEL` (which the network policy selects), and
knows the app's look page as the only place it may open."""

import json
from typing import Any

import pytest
from ashley.looks import pod_spec
from warm_blind_support import CONFIG, IMAGE, PAGE_URL, PREFIX, RUNTIME, SHOOTER_TEXT, TOKEN, with_config


def warm(name: str = "look-warm", config: Any = CONFIG, prefix: str = PREFIX) -> dict[str, Any]:
    return pod_spec.warm_manifest(name, prefix, config, IMAGE, RUNTIME, SHOOTER_TEXT)


def cold() -> dict[str, Any]:
    return pod_spec.manifest("look-x", PAGE_URL, CONFIG, IMAGE, RUNTIME, SHOOTER_TEXT)


def container(pod: dict[str, Any]) -> dict[str, Any]:
    [only] = pod["spec"]["containers"]
    return only


def env(pod: dict[str, Any]) -> dict[str, str]:
    return {e["name"]: e["value"] for e in container(pod).get("env", [])}


def test_it_is_a_pod_with_the_name_it_was_given() -> None:
    pod = warm("look-warm")
    assert pod["kind"] == "Pod" and pod["metadata"]["name"] == "look-warm"
    assert warm("other")["metadata"]["name"] == "other"


def test_it_carries_the_service_s_label_and_the_look_pod_s() -> None:
    labels = warm()["metadata"]["labels"]
    assert labels[pod_spec.WARM_LABEL] == "true"
    assert labels[pod_spec.LABEL] == "true"


def test_the_look_pod_does_not_carry_the_warm_label() -> None:
    assert pod_spec.WARM_LABEL not in cold()["metadata"]["labels"]


def test_the_service_name_and_labels_are_the_documented_ones() -> None:
    assert pod_spec.WARM_SERVICE == "ashley-look-warm"
    assert pod_spec.WARM_LABEL == "ashley.yggdrasil.pub/look-warm"
    assert pod_spec.LABEL == "ashley.yggdrasil.pub/look"


def test_it_restarts_if_its_container_dies_and_has_no_deadline() -> None:
    spec = warm()["spec"]
    assert spec["restartPolicy"] in ("Always", "OnFailure")
    assert "activeDeadlineSeconds" not in spec
    assert cold()["spec"]["restartPolicy"] == "Never"
    assert "activeDeadlineSeconds" in cold()["spec"]


def test_it_is_ready_once_it_answers_healthz() -> None:
    probe = container(warm())["readinessProbe"]
    assert probe["httpGet"]["path"] == "/healthz"
    assert probe["httpGet"]["port"] == 8080


def test_it_serves_on_the_port_the_service_reaches() -> None:
    ports = [p["containerPort"] for p in container(warm()).get("ports", [])]
    assert 8080 in ports


def test_it_runs_the_shooter_in_serve_mode_with_the_look_page_as_its_prefix() -> None:
    pod = warm()
    assert SHOOTER_TEXT in container(pod)["command"] + container(pod).get("args", [])
    assert env(pod)["ASHLEY_LOOK_MODE"] == "serve"
    assert env(pod)["ASHLEY_LOOK_PREFIX"] == PREFIX


def test_it_has_no_page_of_its_own_to_open() -> None:
    pod = warm()
    assert "ASHLEY_LOOK_URL" not in env(pod)
    assert TOKEN not in json.dumps(pod)


def test_the_look_pod_is_not_in_serve_mode() -> None:
    assert env(cold()).get("ASHLEY_LOOK_MODE") != "serve"


def test_the_size_limits_come_in_the_same_json_as_for_a_look_pod() -> None:
    limits = json.loads(env(warm())["ASHLEY_LOOK_LIMITS"])
    assert limits == json.loads(env(cold())["ASHLEY_LOOK_LIMITS"])
    assert set(limits) == {"width", "height", "max_height", "quality", "max_bytes", "ready_s"}
    assert limits["max_bytes"] == CONFIG.max_image_bytes and limits["ready_s"] == CONFIG.ready_timeout_s


@pytest.mark.parametrize("path", [
    ("runtimeClassName",), ("automountServiceAccountToken",), ("hostNetwork",), ("hostPID",), ("hostIPC",),
    ("securityContext",), ("volumes",), ("enableServiceLinks",),
])
def test_the_pod_is_locked_down_as_a_look_pod_is(path: tuple[str, ...]) -> None:
    assert warm()["spec"].get(path[0]) == cold()["spec"].get(path[0])


@pytest.mark.parametrize("key", ["securityContext", "resources", "image", "volumeMounts", "workingDir"])
def test_the_container_is_locked_down_and_limited_as_a_look_pod_s_is(key: str) -> None:
    assert container(warm()).get(key) == container(cold()).get(key)


def test_the_environment_scratch_is_the_look_pod_s() -> None:
    for name in ("HOME", "TMPDIR"):
        assert env(warm())[name] == env(cold())[name]


def test_the_lock_down_itself() -> None:
    spec, c = warm()["spec"], container(warm())
    assert spec["runtimeClassName"] == RUNTIME
    assert spec["automountServiceAccountToken"] is False
    assert c["securityContext"]["readOnlyRootFilesystem"] is True
    assert c["securityContext"]["allowPrivilegeEscalation"] is False
    assert c["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert spec["securityContext"]["runAsNonRoot"] is True
    assert spec["securityContext"]["runAsUser"] == pod_spec.NOBODY
    assert spec["hostNetwork"] is False and spec["hostPID"] is False and spec["hostIPC"] is False


def test_the_pod_waits_for_a_look_at_least_as_long_as_a_page_may_take_to_draw() -> None:
    waits = [float(v) for k, v in env(warm()).items() if k.endswith("WAIT_S")]
    assert waits and all(w > CONFIG.ready_timeout_s for w in waits)


def test_it_is_the_same_manifest_for_the_same_inputs() -> None:
    assert warm() == warm()
    assert json.dumps(warm(), sort_keys=True) == json.dumps(warm(), sort_keys=True)


def test_limits_come_from_the_config() -> None:
    bigger = warm(config=with_config(memory="3Gi", cpu="2"))
    assert container(bigger)["resources"]["limits"]["memory"] == "3Gi"
    assert container(bigger)["resources"]["limits"]["cpu"] == "2"
    assert container(bigger)["resources"] != container(warm())["resources"]


def test_the_prefix_is_whatever_it_is_given() -> None:
    assert env(warm(prefix="http://app.other:81/look/"))["ASHLEY_LOOK_PREFIX"] == "http://app.other:81/look/"

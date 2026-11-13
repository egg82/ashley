"""The warm pod is not the per-look looker's to sweep: `KubernetesLooker` deletes look pods a stopped app pod left
behind once past twice the pod deadline, "the warm pod excepted (its keeper owns it)"."""

import asyncio
from typing import Any

from ashley.looks import pod_spec
from ashley.looks.kubernetes import KubernetesLooker
from ashley.looks.warm_pod import NAME
from warm_blind_support import APP, CONFIG, IMAGE, JPEG, NS, RUNTIME, SHOOTER_TEXT, TARGET, FakeKube, go, line_of

OLD = 2 * CONFIG.pod_deadline_s + 60


class Finishing(FakeKube):
    """Look pods created by the looker finish at once with a picture."""

    async def pod(self, namespace: str, name: str) -> dict[str, Any] | None:
        found = await super().pod(namespace, name)
        if found is not None and name.startswith("look-n"):
            found["status"] = {"phase": "Succeeded"}
        return found

    async def log(self, namespace: str, name: str, limit_bytes: int) -> str:
        return line_of(JPEG)


def cold(kube: FakeKube) -> KubernetesLooker:
    async def no_sleep(seconds: float) -> None:
        await asyncio.sleep(0)

    return KubernetesLooker(kube, NS, RUNTIME, IMAGE, APP, lambda: b"k" * 40, CONFIG, no_sleep)


def test_a_look_pod_past_twice_the_deadline_is_swept_and_the_warm_pod_is_not() -> None:
    kube = Finishing()
    kube.put(pod_spec.warm_manifest(NAME, APP + "/look/", CONFIG, IMAGE, RUNTIME, SHOOTER_TEXT), "Running", age_s=OLD * 10)
    kube.put(pod_spec.manifest("look-left-behind", "u", CONFIG, IMAGE, RUNTIME, SHOOTER_TEXT), "Running", age_s=OLD)
    kube.put(pod_spec.manifest("look-recent", "u", CONFIG, IMAGE, RUNTIME, SHOOTER_TEXT), "Running", age_s=5)
    go(cold(kube).look("look-n1", TARGET))
    assert NAME in kube.pods_by_name
    assert "look-left-behind" not in kube.pods_by_name
    assert "look-recent" in kube.pods_by_name
    assert ("delete", NAME) not in kube.calls


def test_the_warm_pod_survives_any_number_of_looks_of_its_own() -> None:
    kube = Finishing()
    kube.put(pod_spec.warm_manifest(NAME, APP + "/look/", CONFIG, IMAGE, RUNTIME, SHOOTER_TEXT), "Running", age_s=OLD * 10)
    looker = cold(kube)

    async def scenario() -> None:
        for i in range(3):
            await looker.look(f"look-n{i}", TARGET)

    go(scenario())
    assert NAME in kube.pods_by_name

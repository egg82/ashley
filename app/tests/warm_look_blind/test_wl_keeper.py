"""`WarmPod.tick`: look at the pod once and make it right. Create it when there is none; replace one that ended, was
made for another image or limits (its `SPEC_ANNOTATION` differs) or has lived past `warm_max_age_s`; otherwise leave it,
so a holder taking over adopts what is running. A pod already being deleted is left to finish."""

from typing import Any

import pytest
from ashley.looks import pod_spec
from ashley.looks.warm_pod import NAME, SPEC_ANNOTATION
from warm_blind_support import CONFIG, IMAGE, NS, PREFIX, RUNTIME, SHOOTER_TEXT, FakeKube, annotation_of, fields_of, go, keeper, with_config


def wanted() -> dict[str, Any]:
    return pod_spec.warm_manifest(NAME, PREFIX, CONFIG, IMAGE, RUNTIME, SHOOTER_TEXT)


def made_by(image: str = IMAGE, config: Any = CONFIG) -> FakeKube:
    """A cluster holding the pod a keeper of that image and config makes."""
    kube = FakeKube()
    go(keeper(kube, config, image).tick())
    kube.calls.clear()
    return kube


def test_with_no_pod_it_creates_the_warm_pod() -> None:
    kube = FakeKube()
    assert go(keeper(kube).tick()) is False
    assert [m["metadata"]["name"] for m in kube.created] == [NAME]
    assert kube.namespaces == {NS}


def test_the_pod_it_creates_is_the_warm_manifest_with_a_spec_annotation() -> None:
    kube = FakeKube()
    go(keeper(kube).tick())
    made = kube.created[0]
    assert made["spec"] == wanted()["spec"]
    assert made["metadata"]["labels"] == wanted()["metadata"]["labels"]
    assert annotation_of(made)


def test_a_running_pod_of_the_same_spec_is_adopted_untouched() -> None:
    kube = made_by()
    kube.pods_by_name[NAME]["status"]["phase"] = "Running"
    assert go(keeper(kube).tick()) is False
    assert kube.count("create") == 0 and kube.count("delete") == 0


def test_a_pod_still_starting_is_left_alone() -> None:
    kube = made_by()
    assert kube.pods_by_name[NAME]["status"]["phase"] == "Pending"
    go(keeper(kube).tick())
    assert kube.count("create") == 0 and kube.count("delete") == 0


def test_another_holder_of_the_same_inputs_adopts_the_pod_the_first_made() -> None:
    kube = FakeKube()
    go(keeper(kube).tick())
    kube.pods_by_name[NAME]["status"]["phase"] = "Running"
    for _ in range(3):
        go(keeper(kube).tick())
    assert kube.count("create") == 1 and kube.count("delete") == 0


@pytest.mark.parametrize("phase", ["Succeeded", "Failed"])
def test_a_pod_that_ended_is_deleted_then_made_again(phase: str) -> None:
    kube = made_by()
    kube.pods_by_name[NAME]["status"]["phase"] = phase
    pod = keeper(kube)
    assert go(pod.tick()) is True
    assert NAME not in kube.pods_by_name and kube.count("create") == 0
    assert go(pod.tick()) is False
    assert NAME in kube.pods_by_name and kube.count("create") == 1


def test_a_pod_made_for_another_image_is_replaced() -> None:
    kube = made_by(image="registry.test/apps/ashley-look@sha256:" + "b" * 64)
    kube.pods_by_name[NAME]["status"]["phase"] = "Running"
    pod = keeper(kube)
    assert go(pod.tick()) is True
    go(pod.tick())
    assert kube.count("delete") == 1 and kube.count("create") == 1
    assert annotation_of(kube.pods_by_name[NAME]) == annotation_of(made_by().pods_by_name[NAME])
    assert kube.pods_by_name[NAME]["spec"]["containers"][0]["image"] == IMAGE


@pytest.mark.parametrize("changes", [{"memory": "2Gi"}, {"cpu": "2"}, {"cpu_request": "500m"}, {"shm_mib": 512}])
def test_a_pod_made_for_other_limits_is_replaced(changes: dict[str, Any]) -> None:
    kube = made_by(config=with_config(**changes))
    kube.pods_by_name[NAME]["status"]["phase"] = "Running"
    pod = keeper(kube)
    assert go(pod.tick()) is True
    go(pod.tick())
    assert kube.count("delete") == 1 and kube.count("create") == 1


def test_the_annotation_is_the_same_for_the_same_inputs_and_differs_for_other_ones() -> None:
    same = [annotation_of(made_by().pods_by_name[NAME]) for _ in range(2)]
    other_image = annotation_of(made_by(image="registry.test/x@sha256:" + "c" * 64).pods_by_name[NAME])
    other_limits = annotation_of(made_by(config=with_config(memory="3Gi")).pods_by_name[NAME])
    assert same[0] and same[0] == same[1]
    assert len({same[0], other_image, other_limits}) == 3


def test_a_pod_past_the_longest_it_may_live_is_replaced() -> None:
    kube = FakeKube()
    kube.put(made_by().pods_by_name[NAME], age_s=CONFIG.warm_max_age_s + 60)
    pod = keeper(kube)
    assert go(pod.tick()) is True
    go(pod.tick())
    assert kube.count("delete") == 1 and kube.count("create") == 1


def test_a_pod_a_minute_short_of_the_longest_is_kept() -> None:
    kube = FakeKube()
    kube.put(made_by().pods_by_name[NAME], age_s=CONFIG.warm_max_age_s - 60)
    go(keeper(kube).tick())
    assert kube.count("delete") == 0 and kube.count("create") == 0


def test_the_longest_a_pod_lives_is_the_configured_one() -> None:
    config = with_config(warm_max_age_s=600)
    kube = FakeKube()
    kube.put(made_by(config=config).pods_by_name[NAME], age_s=700)
    assert go(keeper(kube, config).tick()) is True
    kube = FakeKube()
    kube.put(made_by(config=config).pods_by_name[NAME], age_s=500)
    assert go(keeper(kube, config).tick()) is False
    assert kube.count("delete") == 0


def test_a_pod_being_deleted_is_left_to_finish() -> None:
    kube = made_by()
    kube.pods_by_name[NAME]["status"]["phase"] = "Running"
    kube.pods_by_name[NAME]["metadata"]["deletionTimestamp"] = "2026-11-02T10:00:00Z"
    assert go(keeper(kube).tick()) is False
    assert kube.count("create") == 0 and kube.count("delete") == 0


def test_a_stale_pod_already_being_deleted_is_not_deleted_again() -> None:
    kube = made_by()
    kube.pods_by_name[NAME]["status"]["phase"] = "Failed"
    kube.pods_by_name[NAME]["metadata"]["deletionTimestamp"] = "2026-11-02T10:00:00Z"
    go(keeper(kube).tick())
    assert kube.count("delete") == 0 and kube.count("create") == 0


def test_a_replacement_waits_for_the_old_pod_to_be_gone_before_creating() -> None:
    kube = made_by()
    kube.terminating = True
    kube.pods_by_name[NAME]["status"]["phase"] = "Failed"
    pod = keeper(kube)
    assert go(pod.tick()) is True
    for _ in range(3):
        go(pod.tick())
    assert kube.count("create") == 0
    assert kube.count("delete") == 1
    del kube.pods_by_name[NAME]
    go(pod.tick())
    assert kube.count("create") == 1


def test_it_never_asks_to_create_a_pod_whose_name_is_taken() -> None:
    kube = made_by()
    kube.pods_by_name[NAME]["status"]["phase"] = "Failed"
    pod = keeper(kube)
    for _ in range(4):
        go(pod.tick())
    taken = [name for verb, name in kube.calls if verb == "create"]
    assert taken.count(NAME) == 1


def test_it_only_ever_touches_its_own_pod() -> None:
    kube = FakeKube()
    kube.put({"metadata": {"name": "look-abc", "labels": {pod_spec.LABEL: "true"}}, "spec": {}})
    kube.put({"metadata": {"name": "run-xyz"}, "spec": {}}, phase="Failed", age_s=10**7)
    go(keeper(kube).tick())
    go(keeper(kube).tick())
    assert {name for verb, name in kube.calls if verb in ("delete", "create")} <= {NAME}
    assert "look-abc" in kube.pods_by_name and "run-xyz" in kube.pods_by_name


def test_each_outcome_is_logged_with_its_event(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    kube = FakeKube()
    pod = keeper(kube)
    go(pod.tick())
    assert len(fields_of(caplog, "looks.warm_started")) == 1
    kube.pods_by_name[NAME]["status"]["phase"] = "Running"
    go(keeper(kube).tick())
    assert len(fields_of(caplog, "looks.warm_adopted")) >= 1
    kube.pods_by_name[NAME]["status"]["phase"] = "Failed"
    go(pod.tick())
    assert len(fields_of(caplog, "looks.warm_replaced")) == 1


def test_a_replacement_names_why_and_the_reasons_differ(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    ended, other, old = made_by(), made_by(image="r/x@sha256:" + "d" * 64), FakeKube()
    ended.pods_by_name[NAME]["status"]["phase"] = "Failed"
    old.put(made_by().pods_by_name[NAME], age_s=CONFIG.warm_max_age_s + 1)
    for kube in (ended, other, old):
        go(keeper(kube).tick())
    reasons = [r.get("reason") for r in fields_of(caplog, "looks.warm_replaced")]
    assert len(reasons) == 3 and all(reasons) and len(set(reasons)) == 3


def test_the_logs_carry_no_page_address_or_prefix(caplog: pytest.LogCaptureFixture) -> None:
    from warm_blind_support import log_text
    caplog.set_level("DEBUG")
    kube = FakeKube()
    pod = keeper(kube)
    go(pod.tick())
    kube.pods_by_name[NAME]["status"]["phase"] = "Failed"
    go(pod.tick())
    text = log_text(caplog)
    assert "/look/" not in text and PREFIX not in text


def test_annotation_name_is_the_documented_one() -> None:
    assert SPEC_ANNOTATION == "ashley.yggdrasil.pub/look-spec"

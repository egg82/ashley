"""`ToolResult.images` on the wire: an Anthropic `tool_result` holds the pictures as image blocks; Chat Completions takes
a tool message as text only, so the pictures follow in one user message, each after a line naming its call; a
checkpoint keeps them, so a resumed turn still has them. The browser pod's spec and log are checked on their contract."""

import base64
import json
from typing import Any

from ashley.channels import checkpoint
from ashley.channels.tool_loop import Progress
from ashley.inference import anthropic_wire, openai_wire
from ashley.inference.openai_wire import PICTURE_LABEL
from ashley.inference.model import Image, Message, SystemPrompt, ToolCall, ToolCalls, ToolResult, ToolResults
from ashley.looks.config import load
from ashley.looks.kubernetes import picture
from ashley.looks.looker import LookUnavailable
from ashley.looks.pod_spec import manifest
import pytest
from respond_support import inbound as respond_inbound

PNG = b"\x89PNG\r\n\x1a\nbytes"
JPG = b"\xff\xd8\xff\xe0jpeg"
CALLS = ToolCalls((ToolCall("a1", "bench_look", {}), ToolCall("b2", "bench_look", {})))


def entries(*results: ToolResult) -> tuple[Any, ...]:
    return (Message("person", "look"), CALLS, ToolResults(tuple(results)))


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def anthropic_blocks(*results: ToolResult) -> list[dict[str, Any]]:
    turns: list[Any] = anthropic_wire.messages(entries(*results))
    last: Any = turns[-1]
    assert last["role"] == "user"
    blocks: list[dict[str, Any]] = list(last["content"])
    return blocks


def test_anthropic_puts_a_pictures_in_its_tool_result_as_image_blocks_after_the_text() -> None:
    (block, _) = anthropic_blocks(ToolResult("a1", "seen", images=(Image("image/png", PNG), Image("image/jpeg", JPG))),
                                  ToolResult("b2", "plain"))
    assert block["type"] == "tool_result" and block["tool_use_id"] == "a1"
    parts = block["content"]
    assert parts[0]["type"] == "text" and parts[0]["text"] == "seen"
    assert [p["type"] for p in parts[1:]] == ["image", "image"]
    assert parts[1]["source"] == {"type": "base64", "media_type": "image/png", "data": b64(PNG)}
    assert parts[2]["source"] == {"type": "base64", "media_type": "image/jpeg", "data": b64(JPG)}


def test_anthropic_leaves_a_result_without_pictures_as_text() -> None:
    (_, plain) = anthropic_blocks(ToolResult("a1", "x", images=(Image("image/png", PNG),)), ToolResult("b2", "plain"))
    assert "image" not in json.dumps(plain) and "plain" in json.dumps(plain)


def test_anthropic_sends_no_picture_outside_the_tool_results() -> None:
    turns: list[Any] = anthropic_wire.messages(entries(ToolResult("a1", "x", images=(Image("image/png", PNG),)), ToolResult("b2", "y")))
    assert len(turns) == 3 and turns[-1]["role"] == "user"
    assert [b["type"] for b in turns[-1]["content"]] == ["tool_result", "tool_result"]


def chat(*results: ToolResult) -> list[Any]:
    return list(openai_wire.messages(SystemPrompt("sys"), entries(*results)))


def test_chat_completions_tool_messages_stay_text_and_pictures_follow_in_one_user_message() -> None:
    got = chat(ToolResult("a1", "seen", images=(Image("image/png", PNG),)), ToolResult("b2", "plain"))
    tools = [m for m in got if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tools] == ["a1", "b2"]
    assert all(isinstance(m["content"], str) and "image" not in json.dumps(m) for m in tools)
    last = got[-1]
    assert last["role"] == "user" and got[-2]["role"] == "tool"
    parts = last["content"]
    assert [p["type"] for p in parts] == ["text", "image_url"]
    assert PICTURE_LABEL in parts[0]["text"] and "a1" in parts[0]["text"]
    assert parts[1]["image_url"]["url"] == f"data:image/png;base64,{b64(PNG)}"


def test_chat_completions_names_the_call_each_picture_came_from() -> None:
    got = chat(ToolResult("a1", "x", images=(Image("image/png", PNG),)), ToolResult("b2", "y", images=(Image("image/jpeg", JPG),)))
    parts = got[-1]["content"]
    assert [p["type"] for p in parts] == ["text", "image_url", "text", "image_url"]
    assert "a1" in parts[0]["text"] and "b2" in parts[2]["text"] and "b2" not in parts[0]["text"]
    assert parts[3]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_chat_completions_sends_no_picture_message_when_there_are_none() -> None:
    got = chat(ToolResult("a1", "x"), ToolResult("b2", "y"))
    assert got[-1]["role"] == "tool" or all(PICTURE_LABEL not in json.dumps(m) for m in got)
    assert all(PICTURE_LABEL not in json.dumps(m) for m in got)


def test_a_checkpoint_keeps_the_pictures_a_round_has_so_far() -> None:
    inbound = respond_inbound("look")
    done = {"a1": ToolResult("a1", "seen", images=(Image("image/png", PNG), Image("image/jpeg", JPG)))}
    progress = Progress((Message("person", "look"),), 1, 1, asked=CALLS, done=done)
    saved = checkpoint.loads(checkpoint.dumps(checkpoint.Checkpoint(inbound, 1, 2, 1, {"default": SystemPrompt("s", "m")}, progress)))
    assert saved.progress.done == done


def test_a_checkpoint_keeps_the_pictures_of_finished_rounds() -> None:
    inbound = respond_inbound("look")
    progress = Progress(entries(ToolResult("a1", "seen", images=(Image("image/png", PNG),)), ToolResult("b2", "y")), 2, 2)
    saved = checkpoint.loads(checkpoint.dumps(checkpoint.Checkpoint(inbound, 1, 2, 1, {"default": SystemPrompt("s")}, progress)))
    assert saved.progress.entries == progress.entries


def spec(**edits: Any) -> dict[str, Any]:
    return manifest("look-abc", "https://app.test/look/TOKEN", load(), "img@sha256:abc", "gvisor", "print(1)", **edits)


def test_the_pod_is_never_restarted_has_a_deadline_and_no_service_account_token() -> None:
    pod = spec()
    assert pod["metadata"]["name"] == "look-abc"
    assert pod["spec"]["restartPolicy"] == "Never"
    assert pod["spec"]["activeDeadlineSeconds"] == load().pod_deadline_s
    assert pod["spec"]["automountServiceAccountToken"] is False
    assert pod["spec"]["runtimeClassName"] == "gvisor"


def test_the_container_is_locked_down_with_a_read_only_root_and_a_writable_home() -> None:
    (container,) = spec()["spec"]["containers"]
    assert container["image"] == "img@sha256:abc"
    sc = container["securityContext"]
    assert sc["readOnlyRootFilesystem"] is True and sc["allowPrivilegeEscalation"] is False
    assert sc["runAsNonRoot"] is True and sc["capabilities"]["drop"] == ["ALL"]
    env = {e["name"]: e.get("value") for e in container["env"]}
    assert env["HOME"] == "/home/look" and env["TMPDIR"] == "/home/look"
    assert env["ASHLEY_LOOK_URL"] == "https://app.test/look/TOKEN"


def test_the_pod_labels_itself_for_the_network_policy_and_carries_the_page_address_only_in_its_env() -> None:
    pod = spec()
    assert "ashley.yggdrasil.pub/look" in pod["metadata"]["labels"]
    assert "TOKEN" not in json.dumps({k: v for k, v in pod.items() if k != "spec"})
    assert json.dumps(pod).count("TOKEN") == 1


def test_the_pods_resources_and_scratch_are_the_configured_ones() -> None:
    cfg = load()
    pod = spec()
    (container,) = pod["spec"]["containers"]
    assert container["resources"]["limits"]["cpu"] == cfg.cpu and container["resources"]["limits"]["memory"] == cfg.memory
    assert container["resources"]["requests"]["cpu"] == cfg.cpu_request
    assert container["resources"]["requests"]["ephemeral-storage"] == container["resources"]["limits"]["ephemeral-storage"] == f"{cfg.ephemeral_mib}Mi"
    volumes = {v["name"]: v for v in pod["spec"]["volumes"]}
    sizes = sorted(v["emptyDir"]["sizeLimit"] for v in volumes.values())
    assert f"{cfg.home_mib}Mi" in sizes and f"{cfg.shm_mib}Mi" in sizes
    shm = [v for v in volumes.values() if v["emptyDir"].get("medium") == "Memory"]
    assert len(shm) == 1 and shm[0]["emptyDir"]["sizeLimit"] == f"{cfg.shm_mib}Mi"


def test_the_pod_log_picture_is_the_base64_after_the_last_marker() -> None:
    from ashley.looks import kubernetes
    first, second = b"\xff\xd8\xff first", b"\xff\xd8\xff second"
    log = f"noise\n{kubernetes.MARK}{b64(first)}\nmore\n{kubernetes.MARK}{b64(second)}\n"
    assert picture(log).data == second


def test_a_failed_line_is_the_reason_the_look_is_unavailable() -> None:
    from ashley.looks import kubernetes
    with pytest.raises(LookUnavailable) as caught:
        picture(f"loading\n{kubernetes.FAILED}not_ready\n")
    assert "not_ready" in str(caught.value)


def test_a_log_with_neither_marker_nor_failure_is_no_picture() -> None:
    with pytest.raises(LookUnavailable) as caught:
        picture("just noise\n")
    assert "no_picture" in str(caught.value)


@pytest.mark.parametrize("line", ["ashley-look @@@not-base64@@@", "ashley-look " + base64.b64encode(b"GIF89a-not-a-jpeg").decode()])
def test_a_marked_line_that_is_no_jpeg_is_no_picture(line: str) -> None:
    with pytest.raises(LookUnavailable):
        picture(f"{line}\n")

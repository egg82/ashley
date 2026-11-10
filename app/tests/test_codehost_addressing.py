"""What may name a project, a path or a ref: refused before a URL is built."""

import pytest
from ashley.codehost import addressing
from ashley.codehost.host import CodeHostFailed
from ashley.codehost.model import Forge


@pytest.mark.parametrize("forge, value", [("gitlab", "grp/sub/proj"), ("gitlab", "42"), ("gitlab", "a/b.c-d_e"),
                                          ("github", "alana/site"), ("github", "alana/.github")])
def test_a_project_of_the_forge_is_taken(forge: Forge, value: str) -> None:
    assert addressing.reason(forge, "project", value) is None


@pytest.mark.parametrize("forge, value, why", [
    ("gitlab", "..", "dot_segment"), ("gitlab", "a/%2E%2e/b", "dot_segment"), ("gitlab", "", "empty_segment"),
    ("gitlab", "a//b", "empty_segment"), ("gitlab", "solo", "shape"), ("gitlab", "a/b c", "shape"),
    ("github", "a/b/c", "shape"), ("github", "../user", "dot_segment"), ("github", "a/%252e%252e", "dot_segment"),
    ("github", "a/b%2fc", "separator"), ("github", "-a/b", "shape")])
def test_a_project_that_is_no_id_of_the_forge_is_refused(forge: Forge, value: str, why: str) -> None:
    assert addressing.reason(forge, "project", value) == why


@pytest.mark.parametrize("value, why", [("a/../b", "dot_segment"), (".", "dot_segment"), ("a//b", "empty_segment"),
                                        ("a/", "empty_segment"), ("%2e%2e/x", "dot_segment"), ("a%5cb", "separator")])
def test_a_path_or_ref_with_a_dot_empty_or_hidden_segment_is_refused(value: str, why: str) -> None:
    assert addressing.reason("github", "path", value) == why
    assert addressing.reason("gitlab", "ref", value) == why


def test_an_empty_path_or_ref_is_the_root_or_default_branch() -> None:
    assert addressing.reason("github", "path", "") is None and addressing.reason("gitlab", "ref", "") is None


def test_segments_are_encoded_one_by_one_and_a_refusal_is_not_found() -> None:
    assert addressing.encoded("feature/a b#c") == "feature/a%20b%23c"
    with pytest.raises(CodeHostFailed) as e:
        addressing.ensure("github", "path", "../x")
    assert e.value.reason == "not_found"

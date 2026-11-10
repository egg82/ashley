"""GitLab and GitHub as connection kinds: a person's own code host, checked by one authenticated read."""

from .. import services
from ..connections.kinds import Check, ConnectionKind, Refusal
from . import github
from .host import CodeHost, CodeHostFailed
from .model import Access, Forge, Reason

_REFUSED: dict[Reason, Refusal] = {"refused": "key_refused", "unreachable": "unreachable", "not_found": "wrong_service",
                                   "unexpected": "wrong_service", "too_large": "unreachable"}


def _check(forge: Forge) -> Check:
    async def check(base: str, token: str, person_id: int) -> Refusal | None:
        try:
            await services.get(CodeHost).check(Access(forge, base, token))
        except CodeHostFailed as e:
            return _REFUSED[e.reason]
        return None
    return check


_READS = "She only reads, only in a chat that is yours alone, and only what your token can."

GITLAB = ConnectionKind(
    name="gitlab", title="GitLab", what="your code",
    blurb=f"Let her read your repositories on GitLab: the projects your token reads, their files, and a file or "
          f"snapshot put on a bench. {_READS}",
    connected="Connected. She can read your repositories in your own chat.",
    removed="Removed. She can’t read your GitLab now.",
    holders=frozenset({"person"}), schemes=frozenset({"https"}), address_placeholder="https://git.example",
    secret_field="token",
    secret_label="Personal access token with read_api and read_repository, from your GitLab profile",
    secret_noun="token", check=_check("gitlab"),
    ports=frozenset({"code_host"}),
    refusals={"bad_url": "the address is an https address of GitLab, with nothing after it but a path",
              "key_refused": "GitLab turned that token away; make a personal access token with read_api and "
                             "read_repository in your GitLab profile",
              "unreachable": "nothing answered at that address in time",
              "wrong_service": "what answered at that address is not GitLab"})

GITHUB = ConnectionKind(
    name="github", title="GitHub", what="your code",
    blurb=f"Let her read your repositories on GitHub: the projects your token reads, their files, and a file or "
          f"snapshot put on a bench. {_READS}",
    connected="Connected. She can read your repositories in your own chat.",
    removed="Removed. She can’t read your GitHub now.",
    holders=frozenset({"person"}), schemes=frozenset(), address_placeholder="", fixed_address=github.API,
    secret_field="token",
    secret_label="Fine-grained token with read-only Contents and Metadata, from your GitHub settings",
    secret_noun="token", check=_check("github"),
    ports=frozenset({"code_host"}),
    refusals={"bad_url": "the address is not GitHub's",
              "key_refused": "GitHub turned that token away; make a fine-grained token with read-only Contents and "
                             "Metadata in your GitHub settings",
              "unreachable": "nothing answered in time",
              "wrong_service": "what answered is not GitHub"})

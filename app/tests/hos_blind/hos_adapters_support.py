"""The adapters' tests share these: the forges and projects they read, the scenario runner over a real
`RoutedCodeHost` on the fake forges, and the failure reason of a call."""

from collections.abc import Awaitable, Callable

from ashley.codehost.config import CodeHostConfig
from ashley.codehost.host import CodeHost, CodeHostFailed
from ashley.codehost.model import Access, Forge, Reason
from hos_support import GH_ALANA, GL_ALANA, SMALL, access_for, go
from hos_forges_support import Forges, standard

FORGES: list[Forge] = ["gitlab", "github"]
TOKEN = {"gitlab": GL_ALANA, "github": GH_ALANA}
PROJECT = {"gitlab": "grp/sub/proj", "github": "alana/site"}
HIDDEN = {"gitlab": "sam/notes", "github": "sam/samrepo"}
API_PREFIX = {"gitlab": "/api/v4/", "github": "/"}
HOST = {"gitlab": "gitlab.test", "github": "api.github.com"}
README = b"# read me\nhello\n"
WEIRD = "weird dir/ünï #1?%.txt"

Scenario = Callable[[CodeHost, Access, Forges], Awaitable[None]]


def run(forge: Forge, scenario: Scenario, forges: Forges | None = None, config: CodeHostConfig = SMALL, token: str = "") -> Forges:
    f = forges if forges is not None else standard()

    async def go_() -> None:
        await scenario(f.routed(config), access_for(forge, token or TOKEN[forge]), f)

    go(go_())
    return f


async def reason_of(call: Awaitable[object]) -> Reason:
    try:
        await call
    except CodeHostFailed as e:
        return e.reason
    raise AssertionError("the call did not fail")

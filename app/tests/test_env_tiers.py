"""Every environment variable `settings.from_env` reads, and which tier of configuration it belongs to
(`docs/decisions.md`, "Env var, file, connection or setting"). A new read fails until it is listed here, which is
the moment to ask whether it is a connection or a setting instead; a listed name nothing reads fails too, so the
list stays what the code is. The names are found by parsing `settings.py` (`env.get("NAME", ...)` and
`env["NAME"]`), never by matching text.

Tiers: `deployment` (the process needs it before it can reach its database, or it names this deployment), `overlay`
(the path of an operator file laid over a shipped data file), `seed` (an env value that seeds a connection row, after
which the row wins). A name whose identifier ends `_KEY`, `_TOKEN`, `_SECRET` or `_PASSWORD` must be a `seed` naming a registered
connection kind, a `ROOT_SECRETS` entry with its reason, or `TO_MOVE` debt recorded in `docs/open-work.md` item 42."""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.reads_docs  # run on a docs-only pull request (ci.yml)

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "ashley" / "settings.py"
TIERS = {"deployment", "overlay", "seed"}
MIN_FOUND = 40

D, O, S = "deployment", "overlay", "seed"
ENV: dict[str, tuple[str, str]] = {
    "DATABASE_URL": (D, "the database the process cannot start without"),
    "BUILD_VERSION": (D, "names the running build"),
    "CONNECTIONS_KEY": (D, "seals every connection, so it cannot itself be one"),
    "PUBLIC_URL": (D, "names this deployment to browsers and sign-in providers"),
    "OPERATOR_NAME": (D, "names who runs this deployment, for its legal pages"),
    "OPERATOR_CONTACT": (D, "names who runs this deployment, for its legal pages"),
    "OIDC_ISSUER": (D, "the web sign-in client, needed before anyone can sign in"),
    "OIDC_CLIENT_ID": (D, "the web sign-in client"),
    "OIDC_CLIENT_SECRET": (D, "the web sign-in client"),
    "ADMIN_GROUP": (D, "the web sign-in client: which of the provider's groups makes a person an admin"),
    "DISCORD_OAUTH_CLIENT_ID": (D, "this deployment's Discord sign-in client"),
    "DISCORD_OAUTH_CLIENT_SECRET": (D, "this deployment's Discord sign-in client"),
    "GOOGLE_OAUTH_CLIENT_ID": (D, "this deployment's Google OAuth client; the logins are connections"),
    "GOOGLE_OAUTH_CLIENT_SECRET": (D, "this deployment's Google OAuth client; the logins are connections"),
    "ETCD_URL": (D, "which etcd decides the leading site"),
    "ETCD_CA_FILE": (D, "etcd's TLS files"),
    "ETCD_CERT_FILE": (D, "etcd's TLS files"),
    "ETCD_KEY_FILE": (D, "etcd's TLS files"),
    "SITE": (D, "which site this pod runs on"),
    "ACTIVE_SITE_LEADER_PATH": (D, "names where this deployment's referee keeps the database leader"),
    "ACTIVE_SITE_MEMBER": (D, "names where this deployment's referee keeps the database leader"),
    "FAILBACK": (D, "whether this deployment's Postgres is failed back to the preferred site"),
    "PATRONI_RESTAPI_PASSWORD": (D, "the database cluster's own control credential"),
    "ROUTES_FILE": (O, "the operator's routes laid over the shipped routes.json"),
    "ANTHROPIC_API_KEY": (S, "the first household's provider connection; the row wins"),
    "OPENAI_API_KEY": (S, "the first household's provider connection; the row wins"),
    "GEMINI_API_KEY": (S, "the first household's provider connection; the row wins"),
    "ELEVENLABS_API_KEY": (S, "the first household's provider connection; the row wins"),
    "HA_URL": (S, "the first household's Home Assistant connection; the row wins"),
    "HA_TOKEN": (S, "the first household's Home Assistant connection; the row wins"),
    "LOCAL_LLM_URL": (S, "the first household's OpenAI-compatible connection labelled local; the row wins"),
    "LOCAL_LLM_API_KEY": (S, "the first household's OpenAI-compatible connection labelled local; the row wins"),
    "WYOMING_STT_URL": (S, "the first household's Wyoming speech-to-text connection; the row wins"),
    "SEARXNG_URL": (S, "the first household's SearXNG connection; the row wins"),
    "DISCORD_BOT_TOKEN": (S, "the first household's Discord connection; the row wins"),
    "ESPHOME_NOISE_PSK": (S, "the first household's satellites connection; the row wins"),
    "FILES_ENDPOINTS": (S, "the first household's file storage connection; the row wins"),
    "FILES_BUCKET": (S, "the first household's file storage connection; the row wins"),
    "FILES_ACCESS_KEY": (S, "the first household's file storage connection; the row wins"),
    "FILES_SECRET_KEY": (S, "the first household's file storage connection; the row wins"),
    "FILES_LINK_KEY": (D, "signs this deployment's file links"),
    "VOICE_CLIP_BASE_URL": (D, "names where this deployment serves clips to satellites"),
    "VAPID_PUBLIC_KEY": (D, "this deployment's web-push identity"),
    "VAPID_PRIVATE_KEY": (D, "this deployment's web-push identity"),
    "VAPID_SUBJECT": (D, "this deployment's web-push identity"),
    "HERDR_CLIENT_CERT_FILE": (D, "the TLS identity this deployment presents to herdr"),
    "HERDR_CLIENT_KEY_FILE": (D, "the TLS identity this deployment presents to herdr"),
    "SANDBOX_TOKEN_FILE": (D, "infra placement: the cluster credential for code runs"),
    "SANDBOX_CA_FILE": (D, "infra placement: the cluster's CA"),
    "SANDBOX_PODMAN": (D, "infra placement: an owner's opt-in to run code with podman on this machine"),
    "SANDBOX_API_URL": (D, "infra placement: the in-cluster API"),
    "SANDBOX_NAMESPACE": (D, "infra placement"),
    "SANDBOX_RUNTIME_CLASS": (D, "infra placement"),
    "MEDIA_IMAGE": (D, "infra placement: an image pinned by digest"),
    "MEDIA_APP_URL": (D, "infra placement: an in-cluster URL"),
    "LOOK_IMAGE": (D, "infra placement: an image pinned by digest"),
    "CAD_IMAGE": (D, "infra placement: an image pinned by digest"),
    "LOOK_APP_URL": (D, "infra placement: an in-cluster URL"),
    "LOOK_WARM_URL": (D, "infra placement: an in-cluster URL"),
    "MAIL_BRIDGE_IMAGE": (D, "infra placement: an image pinned by digest"),
    "MAIL_BRIDGE_NAMESPACE": (D, "infra placement"),
    "MAIL_BRIDGE_APP_URL": (D, "infra placement: an in-cluster URL"),
    "MAIL_BRIDGE_KEEPER_URL": (D, "infra placement: an in-cluster URL"),
    "EMBED_MODELS_DIR": (D, "where this deployment keeps its model files"),
    "VOICEPRINT_MODEL_PATH": (D, "where this deployment keeps its model files"),
}

SEEDS: dict[str, str] = {
    "ANTHROPIC_API_KEY": "anthropic", "OPENAI_API_KEY": "openai", "GEMINI_API_KEY": "gemini",
    "ELEVENLABS_API_KEY": "elevenlabs", "HA_URL": "home_assistant", "HA_TOKEN": "home_assistant",
    "LOCAL_LLM_URL": "openai_compatible", "LOCAL_LLM_API_KEY": "openai_compatible",
    "WYOMING_STT_URL": "wyoming", "SEARXNG_URL": "searxng",
    "DISCORD_BOT_TOKEN": "discord", "ESPHOME_NOISE_PSK": "esphome",
    "FILES_ENDPOINTS": "files", "FILES_BUCKET": "files", "FILES_ACCESS_KEY": "files", "FILES_SECRET_KEY": "files",
}
"""The connection kind each seed names; it must be a kind the app registers."""

ROOT_SECRETS: dict[str, str] = {
    "CONNECTIONS_KEY": "seals the connections table, so it cannot be read from it",
    "PATRONI_RESTAPI_PASSWORD": "controls the database cluster the process must reach first",
    "OIDC_CLIENT_SECRET": "the sign-in client, used before any person or connection exists",
    "DISCORD_OAUTH_CLIENT_SECRET": "the deployment's registered OAuth app, as the sign-in client is",
    "GOOGLE_OAUTH_CLIENT_SECRET": "the deployment's registered OAuth app, as the sign-in client is",
}
"""Secrets that cannot live in the database. Each needs its reason; a credential an outside service holds for a
person or a household is a connection, never an entry here."""

TO_MOVE: set[str] = {
    "FILES_LINK_KEY", "VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY",
}
"""Names that fail the rule today: debt, not approval. Each must be named in backticks in `docs/open-work.md`, and
an entry is removed when its value moves."""

SECRET_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")
OPEN_WORK = ROOT.parent / "docs" / "open-work.md"


def env_names(tree: ast.AST) -> set[str]:
    """The names read as `env.get("NAME", ...)` or `env["NAME"]`, wherever in the tree."""
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" \
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "env" and n.args \
                and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
            out.add(n.args[0].value)
        elif isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == "env" \
                and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str):
            out.add(n.slice.value)
    return out


def found() -> set[str]:
    return env_names(ast.parse(SETTINGS.read_text()))


def test_the_finder_sees_both_read_shapes_and_nothing_else() -> None:
    planted = ast.parse('env.get("A_GET", "")\nenv["A_SUB"]\nother.get("NOT_ENV")\nenv.get(name)\nenv.pop("NOT_READ")')
    assert env_names(planted) == {"A_GET", "A_SUB"}


def test_it_finds_the_names_settings_reads() -> None:
    assert len(found()) >= MIN_FOUND


def test_every_env_var_read_is_listed() -> None:
    unlisted = sorted(found() - ENV.keys())
    assert not unlisted, (f"env vars read but not listed: {unlisted}. Decide each one's tier: is it a connection or "
                          "an in-app setting instead? An env var is only for what the process needs before it can "
                          "reach its database, or what names this deployment (docs/decisions.md)")


def test_every_listed_env_var_is_read() -> None:
    stale = sorted(ENV.keys() - found())
    assert not stale, f"listed but no longer read by settings.py, remove: {stale}"


def test_every_entry_has_a_known_tier_and_a_reason() -> None:
    bad = sorted(k for k, (tier, why) in ENV.items() if tier not in TIERS or not why.strip())
    assert not bad, f"entries without a tier in {sorted(TIERS)} or a reason: {bad}"


def is_secret(name: str) -> bool:
    return name.endswith(SECRET_SUFFIXES)


def secret_problems(env: dict[str, tuple[str, str]], seeds: dict[str, str], roots: dict[str, str], to_move: set[str],
                    kinds: set[str], recorded: set[str]) -> list[str]:
    """What is wrong with the credential-shaped names of `env`, as one line each."""
    out: list[str] = []
    for name, (tier, _) in sorted(env.items()):
        if name in to_move:
            if name not in recorded:
                out.append(f"{name} is TO_MOVE but docs/open-work.md names no `{name}`: record the debt there or move it")
            if tier == "seed" or name in seeds or name in roots:
                out.append(f"{name} is TO_MOVE and also seeded or a root secret: drop the TO_MOVE entry")
        elif name in seeds:
            if tier != "seed" or seeds[name] not in kinds:
                out.append(f"{name} must be tier seed naming a registered connection kind, not {seeds[name]!r}")
        elif name in roots:
            if not roots[name].strip():
                out.append(f"{name} is a root secret with no reason")
        elif is_secret(name):
            out.append(f"{name} is a credential: make it a seed of a connection kind, or a root secret if it cannot "
                       "live in the database, or queue it as TO_MOVE")
    return out


def registered_kinds() -> set[str]:
    from ashley.inference.kinds import KEYED
    from ashley.wiring import CONNECTION_KINDS
    return {k.name for k in CONNECTION_KINDS} | {k.kind.name for k in KEYED}


def recorded_in_open_work() -> set[str]:
    return {t for t in TO_MOVE if f"`{t}`" in OPEN_WORK.read_text()}


def test_credentials_are_seeds_roots_or_recorded_debt() -> None:
    problems = secret_problems(ENV, SEEDS, ROOT_SECRETS, TO_MOVE, registered_kinds(), recorded_in_open_work())
    assert not problems, "\n".join(problems)
    assert sum(is_secret(n) for n in ENV) >= 10


def test_the_markers_name_listed_variables_only() -> None:
    for group in (SEEDS.keys(), ROOT_SECRETS.keys(), TO_MOVE):
        assert not sorted(set(group) - ENV.keys())
    assert not sorted(k for k, t in ENV.items() if (k in SEEDS) != (t[0] == "seed"))


def test_an_unlisted_credential_shape_fails() -> None:
    env = {"NEW_API_KEY": ("deployment", "convenient")}
    assert secret_problems(env, {}, {}, set(), {"anthropic"}, set())
    assert secret_problems({"NEW_API_KEY": ("seed", "x")}, {"NEW_API_KEY": "nonesuch"}, {}, set(), {"anthropic"}, set())
    assert not secret_problems({"NEW_API_KEY": ("seed", "x")}, {"NEW_API_KEY": "anthropic"}, {}, set(), {"anthropic"}, set())


def test_debt_must_be_recorded() -> None:
    env = {"OLD_TOKEN": ("deployment", "x")}
    assert secret_problems(env, {}, {}, {"OLD_TOKEN"}, set(), set())
    assert not secret_problems(env, {}, {}, {"OLD_TOKEN"}, set(), {"OLD_TOKEN"})

"""Process configuration, read once from the environment."""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

DNS_LABEL = re.compile(r"[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?")
DNS_NAME = re.compile(r"[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?")


@dataclass(frozen=True)
class Settings:
    """`database_url` is a libpq connection string; production lists both sites and sets
    `target_session_attrs=read-write`, so a connection always lands on the primary.
    `build_version` names the image that is running.
    `etcd_url` is this site's member of the 3-site etcd (`https://<ip>:2379`); empty, singletons hold Postgres advisory
    locks instead (`ashley.referee.postgres_lease`) and fail-back does not run. The three file paths are its CA and this client's certificate and key, needed for `https`.
    `site` is this site's Patroni member name (`site-a`, `site-b`): singletons run only while it leads.
    `active_site_leader_path` is the etcd key the referee keeps the database leader in, and `active_site_member` the value that
    names this site there (`ACTIVE_SITE_MEMBER`, defaulting to `site`; `active_member` reads it); defaults are the Patroni
    layout. `failback` is `on` or `off` (ValueError otherwise): off, the fail-back singleton does not run, for a Postgres
    whose own operator decides the preferred site.
    `patroni_password` is Patroni's REST API password, which the fail-back singleton needs to switch over.
    `anthropic_api_key`, `openai_api_key`, `gemini_api_key` and `elevenlabs_api_key` are the env's keys for those
    providers: in force wherever the first household has no connection of the provider's kind, and sealed as that
    connection at start (`ashley.inference.key_seed`); once a row exists it wins. `local_llm_url` (with
    `local_llm_api_key`, which a local server may not need) wires a local provider when set.
    `routes_file` is a path to the operator's overlay of the shipped routes (`ashley.inference.routes.overlay`).
    `ha_url` (`http://homeassistant.local:8123`) and `ha_token` (a long-lived access token) wire Home Assistant's tools and
    presence; both or neither, since one without the other can reach nothing (ValueError).
    `wyoming_stt_url` (`tcp://host:port`) seeds the Wyoming speech-to-text connection at start (`ashley.connections.address_seed`);
    once a row exists it wins, and with none and no row the provider is not wired. OpenAI
    transcription needs only OpenAI's key, ElevenLabs' speech only its key.
    `voice_clip_base_url` (`https://ashley.example.com`) is where satellites and room speakers fetch her spoken
    replies; set, and with etcd, the satellite connections singleton runs. It needs `esphome_noise_psk`, the satellites'
    ESPHome API encryption key, since their audio never crosses the network unencrypted (ValueError).
    `discord_bot_token` is her Discord bot's token; set, and with etcd, the Discord singleton runs.
    `oidc_issuer`, `oidc_client_id` and `oidc_client_secret` wire sign-in through OIDC, all three or none
    (ValueError); unset, the sign-in routes answer 503. It needs `public_url` (`https://ashley.example.com`), the
    origin people reach her at, which names the callback the provider returns to and the one origin a cookie-signed write
    may come from (ValueError). `admin_group` names a group in the provider's `groups` claim: set, that group alone
    decides who is an admin of the deployment, read at each sign-in (the `groups` scope is asked for too); empty, the
    app keeps its own record, the first person to sign in on a deployment with no admin becoming one.
    `discord_oauth_client_id` and `discord_oauth_client_secret` are the Discord application's OAuth2 client, through
    which a signed-in person links their own Discord account; both or neither (ValueError), and they need
    `public_url`, which names the redirect Discord returns to (ValueError). Unset, linking answers 503.
    `google_oauth_client_id` and `google_oauth_client_secret` are the Google OAuth client a person connects their
    Google account through; both or neither and they need `public_url`, as Discord's do (ValueError). Unset, connecting
    Google answers 503.
    `operator_name` (who runs the deployment and for whom: `Sam Doe for the Doe household`) and `operator_contact` (an
    email address) fill the public privacy and terms pages; unset, they name the deployment's operator generically.
    `vapid_public_key`, `vapid_private_key` and `vapid_subject` (`mailto:...`) are her Web Push identity; unset, the
    push routes answer 503 and nothing is pushed (`ashley.channels.push.config.vapid` says whether they are usable).
    `sandbox_token_file` is where the app's ServiceAccount token for the sandbox is projected, and `sandbox_ca_file`
    the cluster's CA beside it; set, code runs in pods in the sandbox namespace (`ashley.runs.kubernetes`) through the
    API server at `sandbox_api_url`. Unset, she runs no code. The token file needs its CA (ValueError).
    `sandbox_podman` is `trusted` to run code with podman on this machine (`ashley.runs.podman`) instead, with no
    Kubernetes: podman has no gVisor, so code she runs gets this machine's kernel; it is for one owner who trusts every
    script as much as their own. It excludes the sandbox settings (ValueError), and the screenshots, media and CAD
    image that need them stay off. Any other value is a ValueError; unset, nothing changes.
    `sandbox_namespace` is the namespace every sandbox, look and media pod is made in and `sandbox_runtime_class` the
    RuntimeClass they run under (gVisor); a Kubernetes name each, as the API takes it (ValueError).
    `look_image` (a browser image with Playwright for Python, pinned by digest) and `look_app_url` (where a pod in the
    sandbox namespace reaches the app, `http://host:port`) let her take screenshots of a bench in pods of that namespace
    (`ashley.looks.kubernetes`); both or neither, and they need the sandbox settings and the download-link key
    (ValueError); wiring refuses an image not pinned by digest (ValueError). Unset, she can look at an image piece but not draw a bench.
    `look_warm_url` (the Service of the warm look pod in the sandbox namespace, `http://host:port`) keeps one such pod up
    per site and sends looks to it (`ashley.looks.warm_looker`); it needs `look_image` (ValueError); the wired `Lease` holds the pod,
    per site under etcd and once under Postgres advisory locks. Unset, every look has a pod of its own.
    `cad_image` (Python with build123d and `ashley_cad`, pinned by digest) is the image of the build123d language of the same
    sandbox, run in pods of the same namespace under the same rules; it needs the sandbox settings (ValueError) and wiring
    refuses an image not pinned by digest (ValueError). Unset, the sandbox runs Python only.
    `media_image` (Python with ffmpeg and the Wyoming client, pinned by digest) and `media_app_url` (where a pod in the sandbox
    namespace reaches the app) let her take frames of a video and transcribe a recording in pods of that namespace
    (`ashley.runs.media_kubernetes`); both or neither, and they need the sandbox settings and the download-link key
    (ValueError); wiring refuses an image not pinned by digest (ValueError). The pod reaches the speech service at
    the Wyoming connection's address (`wyoming_stt_url` until there is a row); without one a recording is transcribed only from captions it carries.
    `mail_bridge_image` (Proton Mail Bridge and its keeper, `apps/ashley-mail-bridge`, pinned by digest) keeps one Bridge pod,
    as a singleton under the lease, in `mail_bridge_namespace`, which reaches the app at `mail_bridge_app_url`
    (`https://host`, a certificate the image's trust store accepts); the room's login reaches the keeper at
    `mail_bridge_keeper_url`, a comma-separated list of `https://host:port` addresses of each site's own Service for the
    Bridge pod (this site's first; the pod runs in one cluster, so no one address reaches it from both): the login and
    the mail ports try them in order. Every entry is refused unless `https` (ValueError). All five, and the sandbox settings and `connections_key`, or none (ValueError);
    the wired `Lease` holds the pod, and the keeper's site is `site`, or `local` without etcd;
    wiring refuses an image not pinned by digest (ValueError). Unset, no Proton kind is offered.
    `connections_key` is the app's key for households' connections (`ashley.connections.sealing`), standard base64
    of 32 bytes (wiring raises ValueError otherwise); unset, no connection can be added or read.
    `files_endpoints` (comma-separated `http(s)://host:port` of S3-compatible storage, this site's first and the
    other sites' after), `files_bucket`, `files_access_key`, `files_secret_key` and `files_link_key` (a secret shared
    by every pod, base64 or any text of 32 or more characters, that signs download links) wire the object store behind a
    bench's image and file pieces; all five or none (ValueError). Unset, no file can be taken and no link is minted.
    `herdr_client_cert_file` and `herdr_client_key_file` are the client certificate (issued by the `ashley-bridges` CA)
    and key she presents to a person's herdr bridge (`ashley.herdr`); both or neither (ValueError). Unset, no bridge
    can be reached.
    `embed_models_dir` is where the image keeps the embedding model, read with no network; the default is where
    `app/Containerfile` puts it. `voiceprint_model_path` is the speaker-embedding model file there, likewise."""

    database_url: str
    build_version: str
    etcd_url: str = ""
    etcd_ca_file: str = ""
    etcd_cert_file: str = ""
    etcd_key_file: str = ""
    site: str = ""
    active_site_leader_path: str = "/service/postgres/leader"
    active_site_member: str = ""
    failback: str = "on"
    patroni_password: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    local_llm_url: str = ""
    local_llm_api_key: str = ""
    routes_file: str = ""
    ha_url: str = ""
    ha_token: str = ""
    wyoming_stt_url: str = ""
    elevenlabs_api_key: str = ""
    voice_clip_base_url: str = ""
    esphome_noise_psk: str = ""
    discord_bot_token: str = ""
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    admin_group: str = ""
    discord_oauth_client_id: str = ""
    discord_oauth_client_secret: str = ""
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    public_url: str = ""
    operator_name: str = ""
    operator_contact: str = ""
    searxng_url: str = ""
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = ""
    sandbox_token_file: str = ""
    sandbox_ca_file: str = ""
    sandbox_podman: str = ""
    sandbox_api_url: str = "https://kubernetes.default.svc"
    sandbox_namespace: str = "ashley-sandbox"
    sandbox_runtime_class: str = "gvisor"
    look_image: str = ""
    cad_image: str = ""
    look_app_url: str = ""
    look_warm_url: str = ""
    media_image: str = ""
    media_app_url: str = ""
    mail_bridge_image: str = ""
    mail_bridge_namespace: str = ""
    mail_bridge_app_url: str = ""
    mail_bridge_keeper_url: str = ""
    connections_key: str = field(default="", repr=False)
    files_endpoints: str = ""
    files_bucket: str = ""
    files_access_key: str = field(default="", repr=False)
    files_secret_key: str = field(default="", repr=False)
    files_link_key: str = field(default="", repr=False)
    herdr_client_cert_file: str = ""
    herdr_client_key_file: str = ""
    embed_models_dir: str = "/opt/ashley/models"
    voiceprint_model_path: str = "/opt/ashley/models/voiceprint/nemo_en_titanet_small.onnx"

    @property
    def mail_bridge_keeper_urls(self) -> tuple[str, ...]:
        """`mail_bridge_keeper_url` as its addresses, in order, each without a trailing slash."""
        return tuple(u.strip().rstrip("/") for u in self.mail_bridge_keeper_url.split(",")) if self.mail_bridge_keeper_url else ()

    @property
    def mail_bridge_hosts(self) -> tuple[str, ...]:
        """The host of each address in `mail_bridge_keeper_urls`, in order: where Bridge's IMAP and SMTP are."""
        return tuple(h for h in (urlsplit(u).hostname for u in self.mail_bridge_keeper_urls) if h)

    @property
    def active_member(self) -> str:
        """The value of `active_site_leader_path` that makes this site the active one."""
        return self.active_site_member or self.site

    def __post_init__(self) -> None:
        if self.failback not in ("on", "off"):
            raise ValueError("FAILBACK must be on or off")
        if bool(self.ha_url) != bool(self.ha_token):
            raise ValueError("HA_URL and HA_TOKEN must be set together")
        if self.voice_clip_base_url and not self.esphome_noise_psk:
            raise ValueError("VOICE_CLIP_BASE_URL needs ESPHOME_NOISE_PSK")
        oidc = (self.oidc_issuer, self.oidc_client_id, self.oidc_client_secret)
        if any(oidc) and not all(oidc):
            raise ValueError("OIDC_ISSUER, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET must be set together")
        if all(oidc) and not self.public_url:
            raise ValueError("OIDC_ISSUER needs PUBLIC_URL")
        if bool(self.discord_oauth_client_id) != bool(self.discord_oauth_client_secret):
            raise ValueError("DISCORD_OAUTH_CLIENT_ID and DISCORD_OAUTH_CLIENT_SECRET must be set together")
        if self.discord_oauth_client_id and not self.public_url:
            raise ValueError("DISCORD_OAUTH_CLIENT_ID needs PUBLIC_URL")
        if bool(self.google_oauth_client_id) != bool(self.google_oauth_client_secret):
            raise ValueError("GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET must be set together")
        if self.google_oauth_client_id and not self.public_url:
            raise ValueError("GOOGLE_OAUTH_CLIENT_ID needs PUBLIC_URL")
        files = (self.files_endpoints, self.files_bucket, self.files_access_key, self.files_secret_key,
                 self.files_link_key)
        if any(files) and not all(files):
            raise ValueError("FILES_ENDPOINTS, FILES_BUCKET, FILES_ACCESS_KEY, FILES_SECRET_KEY and FILES_LINK_KEY "
                             "must be set together")
        if self.files_link_key and len(self.files_link_key) < 32:
            raise ValueError("FILES_LINK_KEY must be at least 32 characters")
        if not DNS_LABEL.fullmatch(self.sandbox_namespace):
            raise ValueError("SANDBOX_NAMESPACE must be a Kubernetes namespace name (lowercase letters, digits and '-')")
        if not DNS_NAME.fullmatch(self.sandbox_runtime_class):
            raise ValueError("SANDBOX_RUNTIME_CLASS must be a Kubernetes name (lowercase letters, digits, '-' and '.')")
        if self.sandbox_podman not in ("", "trusted"):
            raise ValueError("SANDBOX_PODMAN must be `trusted` or unset")
        if self.sandbox_podman and (self.sandbox_token_file or self.sandbox_ca_file):
            raise ValueError("SANDBOX_PODMAN and SANDBOX_TOKEN_FILE (or SANDBOX_CA_FILE) are two different sandboxes; set one")
        if self.sandbox_token_file and not self.sandbox_ca_file:
            raise ValueError("SANDBOX_TOKEN_FILE needs SANDBOX_CA_FILE")
        if bool(self.look_image) != bool(self.look_app_url):
            raise ValueError("LOOK_IMAGE and LOOK_APP_URL must be set together")
        if self.look_image and not (self.sandbox_token_file and self.files_link_key):
            raise ValueError("LOOK_IMAGE needs SANDBOX_TOKEN_FILE and FILES_LINK_KEY")
        if self.look_warm_url and not self.look_image:
            raise ValueError("LOOK_WARM_URL needs LOOK_IMAGE")
        if self.cad_image and not self.sandbox_token_file:
            raise ValueError("CAD_IMAGE needs SANDBOX_TOKEN_FILE")
        bridge = (self.mail_bridge_image, self.mail_bridge_namespace, self.mail_bridge_app_url, self.mail_bridge_keeper_url)
        if any(bridge) and not all(bridge):
            raise ValueError("MAIL_BRIDGE_IMAGE, MAIL_BRIDGE_NAMESPACE, MAIL_BRIDGE_APP_URL and MAIL_BRIDGE_KEEPER_URL "
                             "must be set together")
        if not all(u.startswith("https://") for u in (*self.mail_bridge_keeper_urls, self.mail_bridge_app_url or "https://")):
            raise ValueError("MAIL_BRIDGE_APP_URL and MAIL_BRIDGE_KEEPER_URL must be https")
        if self.mail_bridge_image and not (self.sandbox_token_file and self.connections_key):
            raise ValueError("MAIL_BRIDGE_IMAGE needs SANDBOX_TOKEN_FILE and CONNECTIONS_KEY")
        if bool(self.herdr_client_cert_file) != bool(self.herdr_client_key_file):
            raise ValueError("HERDR_CLIENT_CERT_FILE and HERDR_CLIENT_KEY_FILE must be set together")
        if bool(self.media_image) != bool(self.media_app_url):
            raise ValueError("MEDIA_IMAGE and MEDIA_APP_URL must be set together")
        if self.media_image and not (self.sandbox_token_file and self.files_link_key):
            raise ValueError("MEDIA_IMAGE needs SANDBOX_TOKEN_FILE and FILES_LINK_KEY")


def from_env(env: Mapping[str, str] = os.environ) -> Settings:
    """Raises KeyError naming DATABASE_URL when it is unset; BUILD_VERSION defaults to `dev`, the rest to empty."""
    return Settings(database_url=env["DATABASE_URL"], build_version=env.get("BUILD_VERSION", "dev"),
                    etcd_url=env.get("ETCD_URL", ""), etcd_ca_file=env.get("ETCD_CA_FILE", ""),
                    etcd_cert_file=env.get("ETCD_CERT_FILE", ""), etcd_key_file=env.get("ETCD_KEY_FILE", ""),
                    site=env.get("SITE", ""), active_site_leader_path=env.get("ACTIVE_SITE_LEADER_PATH", Settings.active_site_leader_path),
                    active_site_member=env.get("ACTIVE_SITE_MEMBER", ""), failback=env.get("FAILBACK", "on"),
                    patroni_password=env.get("PATRONI_RESTAPI_PASSWORD", ""),
                    anthropic_api_key=env.get("ANTHROPIC_API_KEY", ""), openai_api_key=env.get("OPENAI_API_KEY", ""),
                    gemini_api_key=env.get("GEMINI_API_KEY", ""), local_llm_url=env.get("LOCAL_LLM_URL", ""),
                    local_llm_api_key=env.get("LOCAL_LLM_API_KEY", ""), routes_file=env.get("ROUTES_FILE", "").strip(),
                    ha_url=env.get("HA_URL", ""), ha_token=env.get("HA_TOKEN", ""),
                    wyoming_stt_url=env.get("WYOMING_STT_URL", ""),
                    elevenlabs_api_key=env.get("ELEVENLABS_API_KEY", ""),
                    voice_clip_base_url=env.get("VOICE_CLIP_BASE_URL", "").rstrip("/"),
                    esphome_noise_psk=env.get("ESPHOME_NOISE_PSK", ""),
                    discord_bot_token=env.get("DISCORD_BOT_TOKEN", ""),
                    oidc_issuer=env.get("OIDC_ISSUER", ""), oidc_client_id=env.get("OIDC_CLIENT_ID", ""),
                    oidc_client_secret=env.get("OIDC_CLIENT_SECRET", ""), admin_group=env.get("ADMIN_GROUP", ""),
                    discord_oauth_client_id=env.get("DISCORD_OAUTH_CLIENT_ID", ""),
                    discord_oauth_client_secret=env.get("DISCORD_OAUTH_CLIENT_SECRET", ""),
                    google_oauth_client_id=env.get("GOOGLE_OAUTH_CLIENT_ID", ""),
                    google_oauth_client_secret=env.get("GOOGLE_OAUTH_CLIENT_SECRET", ""),
                    public_url=env.get("PUBLIC_URL", "").rstrip("/"),
                    operator_name=env.get("OPERATOR_NAME", "").strip(),
                    operator_contact=env.get("OPERATOR_CONTACT", "").strip(),
                    searxng_url=env.get("SEARXNG_URL", "").strip().rstrip("/"),
                    vapid_public_key=env.get("VAPID_PUBLIC_KEY", "").strip(),
                    vapid_private_key=env.get("VAPID_PRIVATE_KEY", "").strip(),
                    vapid_subject=env.get("VAPID_SUBJECT", "").strip(),
                    sandbox_token_file=env.get("SANDBOX_TOKEN_FILE", ""),
                    sandbox_ca_file=env.get("SANDBOX_CA_FILE", ""),
                    sandbox_podman=env.get("SANDBOX_PODMAN", "").strip(),
                    sandbox_api_url=env.get("SANDBOX_API_URL", Settings.sandbox_api_url).rstrip("/"),
                    sandbox_namespace=env.get("SANDBOX_NAMESPACE", Settings.sandbox_namespace).strip(),
                    sandbox_runtime_class=env.get("SANDBOX_RUNTIME_CLASS", Settings.sandbox_runtime_class).strip(),
                    media_image=env.get("MEDIA_IMAGE", "").strip(),
                    media_app_url=env.get("MEDIA_APP_URL", "").strip().rstrip("/"),
                    look_image=env.get("LOOK_IMAGE", "").strip(), cad_image=env.get("CAD_IMAGE", "").strip(),
                    look_app_url=env.get("LOOK_APP_URL", "").strip().rstrip("/"),
                    look_warm_url=env.get("LOOK_WARM_URL", "").strip().rstrip("/"),
                    mail_bridge_image=env.get("MAIL_BRIDGE_IMAGE", "").strip(),
                    mail_bridge_namespace=env.get("MAIL_BRIDGE_NAMESPACE", "").strip(),
                    mail_bridge_app_url=env.get("MAIL_BRIDGE_APP_URL", "").strip().rstrip("/"),
                    mail_bridge_keeper_url=env.get("MAIL_BRIDGE_KEEPER_URL", "").strip(),
                    connections_key=env.get("CONNECTIONS_KEY", "").strip(),
                    files_endpoints=env.get("FILES_ENDPOINTS", "").strip(), files_bucket=env.get("FILES_BUCKET", "").strip(),
                    files_access_key=env.get("FILES_ACCESS_KEY", "").strip(),
                    files_secret_key=env.get("FILES_SECRET_KEY", "").strip(),
                    files_link_key=env.get("FILES_LINK_KEY", "").strip(),
                    herdr_client_cert_file=env.get("HERDR_CLIENT_CERT_FILE", "").strip(),
                    herdr_client_key_file=env.get("HERDR_CLIENT_KEY_FILE", "").strip(),
                    embed_models_dir=env.get("EMBED_MODELS_DIR", Settings.embed_models_dir),
                    voiceprint_model_path=env.get("VOICEPRINT_MODEL_PATH", Settings.voiceprint_model_path))

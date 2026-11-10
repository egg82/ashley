"""The composition root: which implementation answers each service (`ashley.services`). Every entry point calls
`wire` once, the app (`ashley.main.create_app`) and the tools and tests included."""

from collections.abc import Callable, Coroutine
from dataclasses import replace
from functools import partial
from typing import Any

import httpx2

from . import services
from .channels.devices import Devices
from .channels.lexicons import Lexicons
from .channels.postgres_lexicons import PostgresLexicons
from .channels.postgres_devices import PostgresDevices
from .channels.kiosk.device_controls import DeviceControls
from .channels.kiosk.postgres_device_controls import PostgresDeviceControls
from .channels import outbox, resume
from .channels.outbox import Outbox
from .channels.postgres_outbox import PostgresOutbox
from .channels.push import config as push_config
from .channels.spend_report import SpendReport
from .channels.spend_view import SpendView
from .channels.push.postgres_subscriptions import PostgresSubscriptions
from .channels.push.subscriptions import Subscriptions
from .channels.voice import config as voice_config
from .channels.voice.clips import Clips
from .channels.voice.postgres_clips import PostgresClips
from .channels.voice.postgres_voices import PostgresVoices
from .channels.voice.voices import Voices
from .codehost.kinds import GITHUB, GITLAB
from .connections.connections import Connections
from .connections.kinds import ConnectionKind, ConnectionKinds
from .connections.oauth import CALLBACK_PATH as OAUTH_CALLBACK, OAuthProviders
from .connections.oauth_connections import OAuthConnections
from .connections.oauth_postgres import PostgresOAuthConnections
from .connections.pending import ConnectPending
from .connections.pending_postgres import PostgresConnectPending
from .connections.renewal import OAuthRenewal, Renewal
from .connections.postgres import PostgresConnections
from .connections.resources import ConnectionResources
from .connections.resources_postgres import PostgresConnectionResources
from .connections.settings_postgres import PostgresSettingsReader
from .connections.settings_read import SettingsReader
from .connections.settings_write import SettingsWriter
from .connections.settings_write_postgres import PostgresSettingsWriter
from .connections.sealing import VERSION as SEAL_VERSION, Sealer, key_from
from .conversations import policy
from .conversations.conversations import Conversations
from .conversations.inflight import InFlight
from .conversations.postgres import PostgresConversations
from .conversations.postgres_inflight import PostgresInFlight
from .db.database import Database
from .db.pool import PoolDatabase
from .errands.register import register as register_errands
from .files.mirror import MirroredStore
from .files.s3 import S3Store
from .files.store import ObjectStore
from .inference import image_quota, prices, routes as inference_routes, spend_catalog
from .inference.balance import ProviderBalances
from .inference.balance_reader import SourcedBalances
from .inference.image_quota import ImageCap
from .inference.key_seed import seed_from_env as seed_keys_from_env
from .inference.keyed_providers import KeyedProviders
from .inference.kinds import KEYED
from .inference.provider_keys import ConnectionProviderKeys
from .inference.routes import Routes, without_fallback
from .inference.inference import Inference
from .inference.postgres import PostgresSpendLedger
from .inference.router import RoutedInference
from .memory.inference_writer import InferenceFactWriter
from .memory.memory import FactWriter, Memory
from .memory.postgres import PostgresMemory
from .home_assistant import house_values, irreversible, rest_automations, zone
from .initiative.initiative import Initiative, WorthSaying
from .live import live as live_config
from .live.live import Live
from .live.postgres import PostgresLive
from .home_assistant.connected_homes import ConnectedHomes
from .home_assistant.homes import Home, Homes
from .home_assistant.kind import HOME_ASSISTANT
from .home_assistant.seed import seed_from_env
from .people.accounts import Accounts
from .people.household_write import HouseholdWriter
from .people.people import People
from .people.postgres_accounts import PostgresAccounts
from .people.postgres_household_write import PostgresHouseholdWriter
from .people.postgres import PostgresPeople
from .senses.homes_presence import HomesPresence
from .live.postgres_screens import PostgresScreens
from .live.screens import Screens
from .senses.deposits import Deposits
from .senses.postgres_deposits import PostgresDeposits
from .senses.postgres_wakes import PostgresWakes
from .senses.presence import Presence
from .senses.register_proposals import register as register_proposals
from .senses.wakes import Wakes
from .looks.looks import Looks
from .looks.postgres import PostgresLooks
from .runs.postgres import PostgresRuns
from .runs.runs import Runs
from .tidy.register import register as register_tidy
from .settings import Settings
from .wiring_providers import env_keys, providers
from .wiring_bridge import wire_mail_bridge
from .wiring_sandbox import wire_sandbox
from .wiring_singletons import wire_lease
from .signin import policy as signin_policy
from .signin.provider import OidcProvider, Client
from .signin.discord import CALLBACK_PATH as DISCORD_CALLBACK, DiscordOAuth
from .signin.discord_http import App as DiscordApp, HttpDiscordOAuth
from .signin.oidc import Oidc
from .signin.postgres import PostgresSessions
from .signin.sessions import Sessions
from .sure.register import register as register_sure
from .sure.kind import SURE
from .google.kind import GOOGLE
from .google.oauth import NAME as GOOGLE_NAME, App as GoogleApp, GoogleOAuth
from .herdr.kind import HERDR
from .mail import config as mail_config
from .mail.gmail import GmailMailbox
from .mail.gmail_wire import GmailWire
from .mail.imap import ImapMailbox
from .mail.mailbox import Mailbox
from .mail.proton_kind import PROTON
from .mail.routed import RoutedMailbox
from .mail.resources import mailboxes
from .herdr.register import register as register_herdr
from .watches.register import register as register_watches
from .codehost import config as codehost_config
from .codehost.github import GitHubHost
from .codehost.gitlab import GitLabHost
from .codehost.host import CodeHost
from .codehost.routed import RoutedCodeHost
from .codehost.wire import Wire
from .tools import home_assistant_config, house_look_config, house_state_config, look_up_config, money_config, outside_config, search_config
from .tools.action_judge import ActionJudge
from .tools.action_judge_model import ModelActionJudge
from .tools.composite import CompositeTools
from .tools.everyday import Everyday, HomesEveryday
from .tools.house_act import Rules
from .tools.house_tools import HouseTools
from .tools.look_up import LookUpTools
from .tools.look_up_config import LookUpConfig
from .tools.pages import Pages
from .tools.places import PlacesTools
from .skills import config as skills_config, seeds as skills_seeds
from .skills.postgres import PostgresSkills
from .skills.skills import Skills
from .tools.tools import Tools
from .tools.web_search import WebSearchTools
from .printables.config import PrintablesConfig
from .tools import page_reader, printables_fetch, site_probe
from .tools.printables_search import PrintablesSearchTools
from .workshop import rules as workshop_rules
from .workshop.installs import Installs
from .workshop.installs_postgres import PostgresInstalls
from .workshop.postgres import PostgresWorkshop
from .workshop.workshop import Workshop


CONNECTION_KINDS: tuple[ConnectionKind, ...] = (HOME_ASSISTANT, SURE, GITLAB, GITHUB, HERDR,
                                                replace(GOOGLE, resources=mailboxes),
                                                *(k.kind for k in KEYED))  # the panel's order


def _wire_oauth(settings: Settings, sealer: Sealer, closers: list[Callable[[], Coroutine[Any, Any, None]]]) -> None:
    """Connects in flight and renewal of OAuth tokens, and Google's provider when its client is set."""
    sign_in = signin_policy.load()
    services.register(ConnectPending, PostgresConnectPending(services.get(Database), sealer, sign_in.pending_minutes,
                                                             sign_in.max_pending))
    services.register(Renewal, OAuthRenewal(mail_config.load().refresh_margin_s))
    if settings.google_oauth_client_id:
        http = httpx2.AsyncClient(timeout=10.0, follow_redirects=False)
        closers.append(http.aclose)
        redirect = settings.public_url + OAUTH_CALLBACK.format(provider=GOOGLE_NAME)
        google = GoogleOAuth(GoogleApp(settings.google_oauth_client_id, settings.google_oauth_client_secret, redirect),
                             http)
        services.register(OAuthProviders, OAuthProviders({GOOGLE_NAME: google}))


def _wire_connections(settings: Settings) -> list[Callable[[], Coroutine[Any, Any, None]]]:
    """Households' connections sealed under the connections key (ValueError when it is not base64 of 32 bytes), and
    Sure, the code hosts and OAuth reached with them. Returns the closers of their HTTP clients."""
    sealer = Sealer({SEAL_VERSION: key_from(settings.connections_key)})
    stored = PostgresConnections(services.get(Database), sealer)
    services.register(Connections, stored)
    services.register(OAuthConnections, PostgresOAuthConnections(stored, services.get(Database), sealer))
    services.register(ConnectionResources, PostgresConnectionResources(services.get(Database)))
    services.register(SettingsReader, PostgresSettingsReader(services.get(Database)))
    services.register(SettingsWriter, PostgresSettingsWriter(services.get(Database)))
    closers: list[Callable[[], Coroutine[Any, Any, None]]] = []
    _wire_oauth(settings, sealer, closers)
    http = httpx2.AsyncClient(follow_redirects=False)
    register_sure(http, money_config.load().timeout_s)
    hosts = codehost_config.load()
    wire = Wire(http, hosts.timeout_s)
    services.register(CodeHost, RoutedCodeHost({"gitlab": GitLabHost(wire, hosts), "github": GitHubHost(wire, hosts)}))
    mail = mail_config.load()
    adapters: dict[str, Mailbox] = {GOOGLE.name: GmailMailbox(GmailWire(http, mail.timeout_s, mail.message_bytes), mail)}
    if settings.mail_bridge_image:
        adapters[PROTON.name] = ImapMailbox(settings.mail_bridge_hosts, mail)
    services.register(Mailbox, RoutedMailbox(adapters))
    closers.append(http.aclose)
    return closers


def wire_files(settings: Settings) -> Callable[[], Coroutine[Any, Any, None]]:
    """The object store over every endpoint in `files_endpoints`: the one store for a single endpoint, otherwise
    every site's as a `MirroredStore`, this site's first. Returns the closer of the HTTP client."""
    http = httpx2.AsyncClient(timeout=30.0, follow_redirects=False)
    stores: list[ObjectStore] = [S3Store(endpoint.strip(), settings.files_bucket, settings.files_access_key,
                                         settings.files_secret_key, http)
                                 for endpoint in settings.files_endpoints.split(",") if endpoint.strip()]
    services.register(ObjectStore, stores[0] if len(stores) == 1 else MirroredStore(stores))
    return http.aclose


def _wire_devices() -> None:
    """What belongs to a device: its sign-in, its touch controls, the clips it plays and the voices it knows."""
    database = services.get(Database)
    services.register(Devices, PostgresDevices(database))
    services.register(DeviceControls, PostgresDeviceControls(database))
    services.register(Clips, PostgresClips(database, voice_config.load().clip_retention_s))
    services.register(Voices, PostgresVoices(database))


def wire(settings: Settings, narrow: Callable[[Routes], Routes] = without_fallback) -> list[Callable[[], Coroutine[Any, Any, None]]]:
    """Register every service the settings call for. Returns what the process must call on shutdown to release
    the connections `wire` opened itself (the database is closed through its own service). `narrow` reshapes the
    loaded routes before the router is built."""
    closers: list[Callable[[], Coroutine[Any, Any, None]]] = []
    services.register(Database, PoolDatabase(settings.database_url))
    services.register(Conversations, PostgresConversations(services.get(Database), policy.load()))
    services.register(InFlight, PostgresInFlight(services.get(Database), policy.load(), resume.CONFIG.claim_s))
    services.register(People, PostgresPeople(services.get(Database)))
    services.register(Accounts, PostgresAccounts(services.get(Database)))
    services.register(HouseholdWriter, PostgresHouseholdWriter(services.get(Database)))
    services.register(Memory, PostgresMemory(services.get(Database)))
    services.register(FactWriter, InferenceFactWriter())
    _wire_devices()
    services.register(Lexicons, PostgresLexicons(services.get(Database)))
    services.register(Outbox, PostgresOutbox(services.get(Database), outbox.load().stale_s, policy.load()))
    services.register(Sessions, PostgresSessions(services.get(Database), signin_policy.load()))
    services.register(Workshop, PostgresWorkshop(services.get(Database), workshop_rules.load()))
    services.register(Skills, PostgresSkills(services.get(Database), skills_config.load(),
                                             skills_seeds.load(skills_config.load())))
    services.register(Runs, PostgresRuns(services.get(Database)))
    services.register(Looks, PostgresLooks(services.get(Database)))
    register_tidy(services.get(Database))
    services.register(Installs, PostgresInstalls(services.get(Database)))
    services.register(ConnectionKinds, ConnectionKinds(CONNECTION_KINDS))
    if settings.connections_key:
        closers.extend(_wire_connections(settings))
    register_herdr(settings.herdr_client_cert_file, settings.herdr_client_key_file)
    if settings.files_endpoints:
        closers.append(wire_files(settings))
    services.register(Wakes, PostgresWakes(services.get(Database)))
    services.register(Deposits, PostgresDeposits(services.get(Database)))
    register_proposals(services.get(Database), *outside_config.keeps())
    services.register(Initiative, WorthSaying())
    if settings.sandbox_token_file:
        api = wire_sandbox(settings, closers)
        if settings.mail_bridge_image:
            wire_mail_bridge(settings, api)
    live = PostgresLive(settings.database_url, services.get(Database), live_config.load())
    closers.append(live.close)
    services.register(Live, live)
    services.register(Screens, PostgresScreens(services.get(Database)))
    register_errands(services.get(Database))
    register_watches(services.get(Database))
    if push_config.checked(settings) is not None:
        services.register(Subscriptions, PostgresSubscriptions(services.get(Database)))
    if settings.oidc_issuer:
        oidc_http = httpx2.AsyncClient(timeout=10.0, follow_redirects=False)
        closers.append(oidc_http.aclose)
        services.register(Oidc, OidcProvider(Client(settings.oidc_issuer, settings.oidc_client_id,
                                                     settings.oidc_client_secret,
                                                     settings.public_url + "/api/auth/callback"), oidc_http))
    if settings.discord_oauth_client_id:
        discord_http = httpx2.AsyncClient(timeout=10.0, follow_redirects=False)
        closers.append(discord_http.aclose)
        services.register(DiscordOAuth, HttpDiscordOAuth(DiscordApp(
            settings.discord_oauth_client_id, settings.discord_oauth_client_secret,
            settings.public_url + DISCORD_CALLBACK), discord_http))
    _wire_homes(settings, closers)
    _wire_inference(settings, narrow, closers)
    services.register(SpendReport, SpendView(services.get(Database), lambda: services.get(People),
                                             lambda: services.get(ProviderBalances), spend_catalog.load()))
    wire_lease(settings)
    return closers


def _wire_inference(settings: Settings, narrow: Callable[[Routes], Routes],
                    closers: list[Callable[[], Coroutine[Any, Any, None]]]) -> None:
    """The router over the keyless providers and the keyed ones (`ashley.inference.kinds`), whose keys are the first
    household's connections where it has them and the env's elsewhere, read again every `REFRESH_S`; routes are
    checked against every provider a key could turn on. The spend page reads the keyed providers' balances."""
    wired, env = providers(settings), env_keys(settings)
    keyed = KeyedProviders(KEYED, ConnectionProviderKeys(lambda: services.get(Connections), (k.kind.name for k in KEYED),
                                                         env), env)
    closers.append(keyed.close)
    routes = inference_routes.load({**keyed.checkers(), **{p.name: p for p in wired}}, settings.routes_file)
    services.register(Inference, RoutedInference(
        narrow(routes), wired, PostgresSpendLedger(services.get(Database)), prices.load(),
        image_cap=ImageCap(partial(image_quota.drawn, services.get(Database)), image_quota.load()), keyed=keyed))
    services.register(ProviderBalances, SourcedBalances(keyed.balance_sources))


def _wire_homes(settings: Settings, closers: list[Callable[[], Coroutine[Any, Any, None]]]) -> None:
    """Each household's Home Assistant from its connection, the env's (`HA_URL`, `HA_TOKEN`) answering for household 1
    while its connection is not settled; presence and the everyday tools over each household's own, and the action judge
    that a turn which has read outside words asks about a consequential change."""
    env = (settings.ha_url, settings.ha_token) if settings.ha_url else None
    homes = ConnectedHomes(services.get(Connections), rest_automations.load(), env=env)
    closers.append(homes.close)
    services.register(Homes, homes)
    services.register(Presence, HomesPresence(services.get(People)))
    shared, over_house = tools(closers, settings.searxng_url)
    services.register(Tools, shared)
    services.register(ActionJudge, ModelActionJudge())
    services.register(Everyday, HomesEveryday(over_house))


def tools(closers: list[Callable[[], Coroutine[Any, Any, None]]],
          searxng_url: str) -> tuple[Tools, Callable[[Home], Tools]]:
    """The look-up over the web, for a household with no house, and what builds a household's tools over its house:
    the house's tools and the look-up with places near it. All share one search client. The web is searched only
    with `searxng_url` set (`SEARXNG_URL`)."""
    config = search_config.load()
    looking = look_up_config.load()
    house = home_assistant_config.load()
    state = house_state_config.load()
    look = house_look_config.load()
    rules = Rules(house.excluded, (), irreversible.load())
    search_http = httpx2.AsyncClient(headers={"User-Agent": "ashley (household assistant)"})
    closers.append(search_http.aclose)
    web = WebSearchTools(search_http, config, searxng_url) if searxng_url else None
    models = printables_fetch.register(search_http)
    page_reader.register(search_http)
    site_probe.register()

    def look_up(places: Tools | None) -> Tools:
        return LookUpTools(partial(look_up_sources, web, places, models, search_http, looking), looking)

    def over(home: Home) -> Tools:
        places = PlacesTools(search_http, config, partial(zone.home, home.home_assistant))
        return CompositeTools({"house": HouseTools(home.house, rules, look, state, house.guidance, home.household_id,
                                                   values=partial(house_values.read, home.household_id)),
                               "search": look_up(places)})

    return CompositeTools({"search": look_up(None)}), over


def look_up_sources(web: WebSearchTools | None, places: Tools | None, models: PrintablesConfig,
                     http: httpx2.AsyncClient, config: LookUpConfig) -> Tools:
    """One look-up's sources: the web and its pages when wired, numbered for this look-up alone, Printables' models,
    numbered on from them, and places when wired."""
    search: dict[str, Tools] = {} if web is None else {"web": Pages(web, http, config)}
    search["printables"] = PrintablesSearchTools.over(models)
    if places is not None:
        search["places"] = places
    return CompositeTools(search)


def warmups(settings: Settings) -> list[Coroutine[Any, Any, None]]:
    """What every pod runs once at start, for the app to start after `wire`, so the first reply after a deploy does not
    pay for it: the embedding and speaker-embedding models' load; with `HA_URL` set, the env's Home Assistant
    sealed as household 1's connection where it has none (`seed_from_env`); and the env's model provider keys sealed as
    its connections of their kinds where it has none (`ashley.inference.key_seed`). Each is best effort and never
    raises."""
    inference = services.get(Inference)
    running: list[Coroutine[Any, Any, None]] = [inference.warm("embed"), inference.warm("voiceprint")]
    if settings.ha_url:
        running.append(_seed(settings))
    if any(env_keys(settings).values()):
        running.append(_seed_keys(settings))
    return running


async def _seed_keys(settings: Settings) -> None:
    await seed_keys_from_env(services.get(Connections), KEYED, env_keys(settings))


async def _seed(settings: Settings) -> None:
    await seed_from_env(services.get(Connections), settings.ha_url, settings.ha_token)

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
from .channels.postgres_remarks import PostgresRemarks
from .channels.remarks import Remarks
from .channels.push import config as push_config
from .channels.watch_reads import ChannelToolReads
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
from .connections.deployment_secrets import DeploymentSecrets
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
from .files.connected_store import ConnectedStore
from .files.store import ObjectStore
from .files.store_kind import KIND as FILES, Keys
from .inference import spend_catalog
from .inference.balance import ProviderBalances
from .connections.address_in_force import AddressInForce
from .inference.compatible import KIND as COMPATIBLE
from .inference.wyoming_kind import KIND as WYOMING
from .channels.discord.token_kind import KIND as DISCORD
from .channels.voice.key_kind import KIND as SATELLITE_KEY
from .inference.kinds import KEYED
from .inference.routes import Routes, without_fallback
from .inference.inference import Inference
from .memory.inference_writer import InferenceFactWriter
from .memory.memory import FactWriter, Memory
from .memory.postgres import PostgresMemory
from .home_assistant import house_values, irreversible, zone
from .initiative.initiative import Initiative, Scored
from .initiative.weights import WEIGHTS
from .live import live as live_config
from .live.live import Live
from .live.postgres import PostgresLive
from .home_assistant.connected_homes import ConnectedHomes
from .home_assistant.ha_held import SocketStates
from .home_assistant.held_states import HeldStates
from .home_assistant.homes import Home, Homes
from .home_assistant.kind import HOME_ASSISTANT
from .people.accounts import Accounts
from .people.admins import Admins
from .people.household_write import HouseholdWriter
from .people.people import People
from .people.postgres_accounts import PostgresAccounts
from .people.postgres_admins import PostgresAdmins
from .people.postgres_household_write import PostgresHouseholdWriter
from .people.postgres import PostgresPeople
from .senses.calendar import Calendar
from .senses.homes_calendar import HomesCalendar
from .senses.focus import Focus
from .senses.herdr_focus import HerdrFocus
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
from .wiring_discord import wire_discord
from .wiring_inference import wire_inference
from .wiring_secrets import register as register_secrets, settle as settle_secrets
from .wiring_seeds import seeds
from .wiring_bridge import wire_mail_bridge
from .wiring_sandbox import wire_podman_sandbox, wire_sandbox
from .wiring_skills import wire_skills
from .wiring_singletons import wire_lease
from .signin import policy as signin_policy
from .signin.provider import OidcProvider, Client
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
from .watches.tool_reads import ToolReads
from .codehost import config as codehost_config
from .codehost.github import GitHubHost
from .codehost.gitlab import GitLabHost
from .codehost.host import CodeHost
from .codehost.routed import RoutedCodeHost
from .codehost.wire import Wire
from .tools import home_assistant_config, home_location, house_look_config, house_state_config, look_up_config, money_config, outside_config, search_config
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
from .tools.tools import Tools
from .tools.search_connection import KIND as SEARXNG, ConnectedWebSearch
from .tools.web_search import WebSearch
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
                                                *(k.kind for k in KEYED), COMPATIBLE, WYOMING, SEARXNG, DISCORD, FILES, SATELLITE_KEY)  # the panel's order


def configured_kinds(settings: Settings) -> tuple[ConnectionKind, ...]:
    """`CONNECTION_KINDS` and Proton, each marked `configured` by the settings it needs: herdr's client certificate,
    and `MAIL_BRIDGE_IMAGE` for Proton."""
    return (*(replace(k, configured=bool(settings.herdr_client_cert_file)) if k is HERDR else k
              for k in CONNECTION_KINDS),
            replace(PROTON, configured=bool(settings.mail_bridge_image)))


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
    """The object store the first household's connection names (`ashley.files.connected_store`), else the one over
    the env's `files_endpoints`. Returns the closer of the HTTP client."""
    http = httpx2.AsyncClient(timeout=30.0, follow_redirects=False)
    env = Keys(settings.files_endpoints, settings.files_bucket, settings.files_access_key,
               settings.files_secret_key) if settings.files_endpoints else None
    services.register(ObjectStore, ConnectedStore(lambda: services.get(Connections), env, http))
    return http.aclose


def _wire_devices() -> None:
    """What belongs to a device: its sign-in, its touch controls, the clips it plays and the voices it knows."""
    database = services.get(Database)
    services.register(Devices, PostgresDevices(database))
    services.register(DeviceControls, PostgresDeviceControls(database))
    services.register(Clips, PostgresClips(database, voice_config.load().clip_retention_s))
    services.register(Voices, PostgresVoices(database))


def wire(settings: Settings, narrow: Callable[[Routes], Routes] = without_fallback,
         database: Database | None = None) -> list[Callable[[], Coroutine[Any, Any, None]]]:
    """Register every service the settings call for. Returns what the process must call on shutdown to release
    the connections `wire` opened itself (the database is closed through its own service). `narrow` reshapes the
    loaded routes before the router is built; `database` replaces the pool over `settings.database_url`."""
    closers: list[Callable[[], Coroutine[Any, Any, None]]] = []
    services.register(Database, database or PoolDatabase(settings.database_url))
    register_secrets(settings)
    services.register(Conversations, PostgresConversations(services.get(Database), policy.load()))
    services.register(InFlight, PostgresInFlight(services.get(Database), policy.load(), resume.CONFIG.claim_s))
    services.register(People, PostgresPeople(services.get(Database), bool(settings.admin_group)))
    services.register(Admins, PostgresAdmins(services.get(Database)))
    services.register(Accounts, PostgresAccounts(services.get(Database)))
    services.register(HouseholdWriter, PostgresHouseholdWriter(services.get(Database)))
    services.register(Memory, PostgresMemory(services.get(Database)))
    services.register(FactWriter, InferenceFactWriter())
    _wire_devices()
    services.register(Lexicons, PostgresLexicons(services.get(Database)))
    services.register(Outbox, PostgresOutbox(services.get(Database), outbox.load().stale_s, policy.load()))
    services.register(Sessions, PostgresSessions(services.get(Database), signin_policy.load(),
                                                 bool(settings.admin_group)))
    services.register(Workshop, PostgresWorkshop(services.get(Database), workshop_rules.load()))
    wire_skills()
    services.register(Runs, PostgresRuns(services.get(Database)))
    services.register(Looks, PostgresLooks(services.get(Database)))
    register_tidy(services.get(Database))
    services.register(Installs, PostgresInstalls(services.get(Database)))
    services.register(ConnectionKinds, ConnectionKinds(configured_kinds(settings)))
    if settings.connections_key:
        closers.extend(_wire_connections(settings))
    register_herdr(settings.herdr_client_cert_file, settings.herdr_client_key_file)
    if settings.files_endpoints or settings.connections_key:
        closers.append(wire_files(settings))
    services.register(Wakes, PostgresWakes(services.get(Database)))
    services.register(Deposits, PostgresDeposits(services.get(Database)))
    register_proposals(services.get(Database), *outside_config.keeps())
    services.register(Initiative, Scored(WEIGHTS))
    services.register(Remarks, PostgresRemarks(services.get(Database)))
    services.register(Focus, HerdrFocus())
    if settings.sandbox_token_file:
        api = wire_sandbox(settings, closers, AddressInForce(lambda: services.get(Connections), WYOMING.name,
                                                              settings.wyoming_stt_url))
        if settings.mail_bridge_image:
            wire_mail_bridge(settings, api)
    elif settings.sandbox_podman:
        wire_podman_sandbox()
    live = PostgresLive(settings.database_url, services.get(Database), live_config.load())
    closers.append(live.close)
    services.register(Live, live)
    services.register(Screens, PostgresScreens(services.get(Database)))
    register_errands(services.get(Database))
    register_watches(services.get(Database))
    services.register(ToolReads, ChannelToolReads())
    if settings.oidc_issuer:
        oidc_http = httpx2.AsyncClient(timeout=10.0, follow_redirects=False)
        closers.append(oidc_http.aclose)
        services.register(Oidc, OidcProvider(Client(settings.oidc_issuer, settings.oidc_client_id,
                                                     settings.oidc_client_secret,
                                                     settings.public_url + "/api/auth/callback",
                                                     settings.admin_group), oidc_http))
    wire_discord(settings, closers)
    _wire_homes(settings, closers)
    wire_inference(settings, narrow, closers)
    services.register(SpendReport, SpendView(services.get(Database), lambda: services.get(People),
                                             lambda: services.get(ProviderBalances), spend_catalog.load()))
    wire_lease(settings)
    return closers


def _wire_homes(settings: Settings, closers: list[Callable[[], Coroutine[Any, Any, None]]]) -> None:
    """Each household's Home Assistant from its connection, the env's (`HA_URL`, `HA_TOKEN`) answering for household 1
    while its connection is not settled; presence and the everyday tools over each household's own, and the action judge
    that a turn which has read outside words asks about a consequential change."""
    env = (settings.ha_url, settings.ha_token) if settings.ha_url else None
    homes = ConnectedHomes(services.get(Connections), env=env)
    closers.append(homes.close)
    services.register(Homes, homes)
    services.register(HeldStates, SocketStates())
    services.register(Presence, HomesPresence(services.get(People)))
    services.register(Calendar, HomesCalendar())
    shared, over_house, without_house = tools(closers, settings.searxng_url)
    services.register(Tools, shared)
    services.register(ActionJudge, ModelActionJudge())
    services.register(Everyday, HomesEveryday(over_house, without_house))


def tools(closers: list[Callable[[], Coroutine[Any, Any, None]]],
          searxng_url: str) -> tuple[Tools, Callable[[Home], Tools], Callable[[int], Tools]]:
    """The look-up over the web, for a household with no house, and what builds a household's tools over its house:
    the house's tools and the look-up with places near it. All share one search client. The web is searched only
    while there is an address, the SearXNG connection's or `searxng_url` where there is none, read on each use."""
    config = search_config.load()
    looking = look_up_config.load()
    house = home_assistant_config.load()
    state = house_state_config.load()
    look = house_look_config.load()
    rules = Rules(house.excluded, (), irreversible.load())
    search_http = httpx2.AsyncClient(headers={"User-Agent": "ashley (household assistant)"})
    closers.append(search_http.aclose)
    web = ConnectedWebSearch(search_http, config, AddressInForce(lambda: services.get(Connections), SEARXNG.name, searxng_url))
    models = printables_fetch.register(search_http)
    page_reader.register(search_http)
    site_probe.register()

    def look_up(places: Tools | None) -> Tools:
        return LookUpTools(partial(look_up_sources, web, places, models, search_http, looking), looking)

    def over(home: Home) -> Tools:
        places = PlacesTools(search_http, config, partial(zone.home, home.home_assistant),
                              partial(home_location.own, home.household_id))
        return CompositeTools({"house": HouseTools(home.house, rules, look, state, house.guidance, home.household_id,
                                                   values=partial(house_values.read, home.household_id)),
                               "search": look_up(places)})

    def without_house(household_id: int) -> Tools:
        places = PlacesTools(search_http, config, home_location.no_house, partial(home_location.own, household_id))
        return CompositeTools({"search": look_up(places)})

    return CompositeTools({"search": look_up(None)}), over, without_house


def look_up_sources(web: WebSearch | None, places: Tools | None, models: PrintablesConfig,
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
    pay for it: the embedding and speaker-embedding models' load, the env's seeds of connections
    (`ashley.wiring_seeds`), and settling the deployment's own secrets (`ashley.wiring_secrets`), which wires browsers'
    push subscriptions once settled when her VAPID identity is usable. Each is best effort and never raises."""
    inference = services.get(Inference)
    running: list[Coroutine[Any, Any, None]] = [inference.warm("embed"), inference.warm("voiceprint")]
    running.extend(seeds(settings))
    running.extend((settle_secrets(settings), _subscriptions(settings.vapid_subject)))
    return running


async def _subscriptions(subject: str) -> None:
    await services.get(DeploymentSecrets).settled()
    if push_config.identity(subject) is not None:
        services.register(Subscriptions, PostgresSubscriptions(services.get(Database)))


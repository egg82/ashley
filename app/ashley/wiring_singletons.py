"""The `Lease` `wire` registers, the singletons it leaves for the app to start under that lease
(`ashley.main.create_app`), and the etcd TLS both share."""

import asyncio
import logging
from collections.abc import Coroutine
from functools import partial
from typing import Any

import httpx2

from . import logs, services
from .channels import bench_job, errand, outbox, resume
from .channels.discord import bot as discord_bot, client as discord_client, config as discord_config
from .channels.discord.following import follow
from .channels.discord.postgres_seen import PostgresSeen
from .channels.discord.token_in_force import TokenInForce
from .channels.push import config as push_config, later as push_later
from .channels.push.sender import WebPushSender
from .channels.respond import respond
from .channels.voice import config as voice_config, vad
from .channels.voice.connection import EsphomeConnection
from .channels.voice.run import Pipeline
from .channels.voice.satellites import NAME as SATELLITES, Satellites
from .channels.wake import runner as wake_runner
from .conversations import policy
from .connections.connections import Connections
from .db.database import Database
from .files import config as files_config, repair as files_repair, sweep as files_sweep
from .files.intake import PREFIX as FILES_PREFIX
from .files.connected_store import ConnectedStore
from .files.mirror import MirroredStore
from .files.orphans import PostgresCandidates
from .files.store import NullStore, ObjectStore
from .home_assistant.media_player import play_for
from .inference import catalogue_config, catalogue_refresh, catalogue_snapshot, watch as inference_watch
from .inference.postgres_catalogue import PostgresCatalogue
from .looks import warm_pod
from .looks.keys import PREFIX as LOOKS_PREFIX
from .looks.looker import Looker
from .looks.warm_looker import WarmLooker
from .mail import proton_bridge_job
from .mail.proton_bridge_job import BridgeKeeping, Keeping
from .memory import write_job
from .memory.memory import FactWriter
from .referee import failback, failback_policy
from .referee.active_site import ActiveSite
from .referee.etcd_gateway import EtcdTls
from .referee.etcd_lease import EtcdLease
from .referee.hold import EtcdHold
from .referee.lease import Lease
from .referee.patroni_etcd import EtcdPatroni
from .referee.postgres_lease import PostgresLease
from .senses import deposit_sense
from .watches import job as watches_job
from .settings import Settings
from .workshop import rules as workshop_rules
from .workshop.file_references import named_keys

log = logging.getLogger("ashley.wiring_singletons")

# The key prefixes the files repair keeps whole on every site; the sweep lists the files' prefix alone.
REPAIRED_PREFIXES: tuple[str, ...] = (FILES_PREFIX, LOOKS_PREFIX)


def wire_lease(settings: Settings) -> None:
    """With `etcd_url`, the etcd lease, held only on the active site (`active_site_leader_path` holding `active_member`, which
    is `site` unless set; neither set is a ValueError); without it, a Postgres advisory lock per singleton on `database_url`."""
    if settings.etcd_url:
        if not settings.active_member:
            raise ValueError("SITE or ACTIVE_SITE_MEMBER must name this site's database member when ETCD_URL is set")
        site = ActiveSite(settings.active_member, settings.active_site_leader_path)
        services.register(Lease, EtcdLease(settings.etcd_url, site, etcd_tls(settings)))
    else:
        services.register(Lease, PostgresLease(settings.database_url))


def _catalogue_refresh() -> Coroutine[Any, Any, None]:
    config = catalogue_config.load()
    fetch = partial(catalogue_snapshot.fetch, config, httpx2.AsyncClient(follow_redirects=False))
    body = partial(catalogue_refresh.run, config, PostgresCatalogue(services.get(Database)), fetch)
    return services.get(Lease).run(catalogue_refresh.NAME, body)


def singletons(settings: Settings) -> list[Coroutine[Any, Any, None]]:
    """Each singleton running under the wired `Lease` until cancelled, for the app to start after `wire`: fail-back
    when `etcd_url` is set and `failback` is on (it drives Patroni through etcd), and with or without etcd the memory write job, resuming
    turns whose runner stopped, taking up Home Assistant's wakes, watching each provider's failed share of chat calls, fetching the model catalogue, reading Sure for deposits an armed reminder waits on, running the bench jobs she handed to workers, polling the Claude Code sessions she handed work to, checking the watches she keeps, comparing the object store's copies on each site and sweeping the bytes no piece names, each site's warm look pod when `look_warm_url` is set, Proton Bridge's pod when `mail_bridge_image` is set, the satellite connections when `voice_clip_base_url` is set, the
    Discord session on the token in force (`ashley.channels.discord.following`), and web push when her VAPID identity is (`push_config.vapid`)."""
    running: list[Coroutine[Any, Any, None]] = []
    if settings.etcd_url and settings.failback == "off":
        logs.info(log, "failback.off")
    elif settings.etcd_url:
        tls = etcd_tls(settings)
        patroni = EtcdPatroni(settings.etcd_url, tls, auth=("patroni", settings.patroni_password))
        body = failback.FailBack(patroni, EtcdHold(settings.etcd_url, tls), failback_policy.load()).run
        running.append(services.get(Lease).run(failback.NAME, body))
    writer = write_job.WriteJob(services.get(FactWriter), write_job.load(), policy.load()).run
    running.append(services.get(Lease).run(write_job.NAME, writer))
    running.append(services.get(Lease).run(errand.NAME, errand.ErrandJob().run))
    running.append(services.get(Lease).run(bench_job.NAME, bench_job.BenchJobRunner().run))
    running.append(services.get(Lease).run(resume.NAME, resume.run))
    running.append(services.get(Lease).run(inference_watch.NAME, partial(inference_watch.run, inference_watch.load())))
    running.append(_catalogue_refresh())
    running.append(services.get(Lease).run(wake_runner.NAME, wake_runner.run))
    running.append(services.get(Lease).run(deposit_sense.NAME, deposit_sense.run))
    running.append(services.get(Lease).run(watches_job.NAME, watches_job.run))
    looker = services.get(Looker)
    if isinstance(looker, WarmLooker):
        running.append(services.get(Lease).run_on_site(warm_pod.NAME, looker.keeper.run))
    keeping = services.get(Keeping)
    if isinstance(keeping, BridgeKeeping):
        running.append(services.get(Lease).run(proton_bridge_job.NAME, partial(proton_bridge_job.run, keeping)))
    store = services.get(ObjectStore)
    if not isinstance(store, NullStore):
        files = files_config.load()
        if isinstance(store, (MirroredStore, ConnectedStore)):
            running.append(services.get(Lease).run(files_repair.NAME, partial(files_repair.run, store, REPAIRED_PREFIXES, files.repair_interval_s)))
        referenced = partial(named_keys, workshop_rules.load())
        sweeping = partial(files_sweep.run, store, referenced, PostgresCandidates(), files)
        running.append(services.get(Lease).run(files_sweep.NAME, sweeping))
    if settings.voice_clip_base_url:
        running.append(_satellites(settings))
    running.append(_discord(settings.discord_bot_token))
    identity = push_config.vapid(settings)
    if identity is not None:
        config = push_config.load()
        sender = WebPushSender(identity, config.ttl_s, config.timeout_s)
        drain = partial(push_later.drain, sender, config, outbox.load().poll_s, asyncio.sleep)
        running.append(services.get(Lease).run(push_later.NAME, drain))
    return running


def _discord(env_token: str) -> Coroutine[Any, Any, None]:
    config = discord_config.load()

    def session(token: str) -> Coroutine[Any, Any, None]:
        return discord_bot.Bot(discord_client.connect(token), PostgresSeen(services.get(Database)), config,
                               later_poll_s=outbox.load().poll_s).run()
    body = partial(follow, TokenInForce(lambda: services.get(Connections), env_token), session, config.token_poll_s)
    return services.get(Lease).run(discord_bot.NAME, body)


async def _satellites(settings: Settings) -> None:
    """The satellite connections under the lease, each room speaker played on its satellite's household's house."""
    config = voice_config.load()
    pipeline = Pipeline(settings.voice_clip_base_url, config.end_of_speech, respond, play_for, vad.micro_vad,
                        config.speaker, config.playback)
    body = Satellites(lambda satellite: EsphomeConnection(satellite, settings.esphome_noise_psk), pipeline, config,
                      later_poll_s=outbox.load().poll_s).run
    await services.get(Lease).run(SATELLITES, body)


def etcd_tls(settings: Settings) -> EtcdTls | None:
    return EtcdTls.for_url(settings.etcd_url, settings.etcd_ca_file, settings.etcd_cert_file, settings.etcd_key_file)

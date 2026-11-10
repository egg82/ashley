"""Proton Bridge's wiring, when `MAIL_BRIDGE_IMAGE` is set: the record, the login relay to the keeper, the upkeep the
singleton runs (`ashley.wiring_singletons`), and the Proton connection kind, which is offered only from here on."""

from . import services
from .connections.kinds import ConnectionKinds
from .connections.sealing import VERSION as SEAL_VERSION, Sealer, key_from
from .db.database import Database
from .mail import config as mail_config
from .mail.proton_bridge import ProtonBridge
from .mail.proton_bridge_job import BridgeKeeping, Keeping
from .mail.proton_bridge_postgres import PostgresProtonBridge
from .mail.proton_kind import PROTON
from .mail.proton_login import ProtonLogin
from .mail.proton_login_http import KeeperLogin
from .runs.config import PINNED
from .runs.kube_api import KubeApi
from .settings import Settings


def wire_mail_bridge(settings: Settings, api: KubeApi) -> None:
    """Register Bridge's record, login and upkeep, and add the Proton kind. Raises ValueError for an image not pinned by
    digest, or a connections key that is not base64 of 32 bytes."""
    if not PINNED.fullmatch(settings.mail_bridge_image):
        raise ValueError("MAIL_BRIDGE_IMAGE must be pinned by a full digest (name@sha256:<64 lowercase hex>)")
    config = mail_config.load()
    bridge = PostgresProtonBridge(services.get(Database), Sealer({SEAL_VERSION: key_from(settings.connections_key)}))
    services.register(ProtonBridge, bridge)
    services.register(ProtonLogin, KeeperLogin(settings.mail_bridge_keeper_urls, bridge, config.timeout_s))
    services.register(Keeping, BridgeKeeping(bridge, api, settings.mail_bridge_namespace, settings.mail_bridge_image,
                                             settings.mail_bridge_app_url, settings.site, config))
    services.register(ConnectionKinds, ConnectionKinds((*services.get(ConnectionKinds).all(), PROTON)))

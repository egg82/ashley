"""How the herdr bridge is wired: its port over HTTPS with this app's client certificate."""

from .. import services
from . import config
from .bridge import Bridge
from .http_bridge import HttpBridge
from .transport import ClientCertificate


def register(cert_file: str, key_file: str) -> None:
    """Register the Bridge port with the client certificate in `cert_file` and its `key_file`, read at each call so a
    renewed certificate is used without a restart. Both empty: nothing is registered and no bridge can be reached."""
    if cert_file:
        services.register(Bridge, HttpBridge(ClientCertificate(cert_file, key_file), config.load()))

"""The links a sandbox pod's init container fetches a job's inputs by: one `ashley.files.links` token for each, signed
under the app's link key, valid until the pod's deadline has passed, on the address a pod in the sandbox namespace
reaches the app at. Pure; the clock is a parameter."""

from collections.abc import Mapping

from ..files import links
from .model import InputFile

MEDIA_TYPE = "application/octet-stream"


def sign(inputs: Mapping[str, InputFile], app_url: str, key: bytes, expires_at: int) -> dict[str, str]:
    """The URL of each input by name, `app_url` (no trailing slash) followed by the link's path."""
    return {name: app_url + links.mint(key, links.Grant(f.household_id, f.sha256, MEDIA_TYPE, False, expires_at)).url
            for name, f in inputs.items()}

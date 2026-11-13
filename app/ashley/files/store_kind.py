"""The object store as a connection kind of the `files` port: one S3-compatible bucket, reached at one endpoint per site
(`MirroredStore`). It is a `deployment` kind held by the first household. A connection stores one secret, so the bucket
and both keys are sealed together as the JSON `{"bucket": …, "access_key": …, "secret_key": …}` (`Keys`), and the
address is the endpoints, comma-separated, this site's first. Checked by one signed listing at every endpoint."""

import json
from dataclasses import dataclass, field

import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..connections.kinds import ConnectionKind, Refusal
from .s3 import S3Store
from .store import StoreUnavailable

NAME = "files"


@dataclass(frozen=True)
class Keys:
    """Where the store is and how to sign in to it: `endpoints` as the connection's address, comma-separated. The two
    keys are left out of `repr`."""

    endpoints: str
    bucket: str
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)

    def secret(self) -> str:
        """The bucket and keys as the connection's one sealed secret."""
        return json.dumps({"bucket": self.bucket, "access_key": self.access_key, "secret_key": self.secret_key})


class _Secret(BaseModel):
    model_config = ConfigDict(strict=True)
    bucket: str = Field(min_length=1)
    access_key: str = Field(min_length=1)
    secret_key: str = Field(min_length=1)


def keys_of(endpoints: str, secret: str) -> Keys | None:
    """The `Keys` for `endpoints` and a secret as `Keys.secret` writes it; None when the secret is not that JSON object
    with all three fields as non-empty text."""
    try:
        found = _Secret.model_validate_json(secret)
    except ValidationError:
        return None
    return Keys(endpoints, found.bucket, found.access_key, found.secret_key)


async def check(base: str, secret: str, person_id: int) -> Refusal | None:
    """One signed listing of the bucket at each endpoint of `base`: None when every one answers to the keys;
    `key_refused` for a secret that is not the JSON shape or keys an endpoint turns away; `wrong_service` when an
    endpoint has no such bucket; `unreachable` for no answer in time or any other status."""
    keys = keys_of(base, secret)
    if keys is None:
        return "key_refused"
    async with httpx2.AsyncClient(timeout=10.0, follow_redirects=False) as http:
        for endpoint in base.split(","):
            try:
                status = await S3Store(endpoint, keys.bucket, keys.access_key, keys.secret_key, http).probe()
            except StoreUnavailable:
                return "unreachable"
            if status == 403:
                return "key_refused"
            if status == 404:
                return "wrong_service"
            if status != 200:
                return "unreachable"
    return None


KIND = ConnectionKind(
    name=NAME, title="File storage", what="her file storage",
    blurb="An S3-compatible bucket (MinIO, Garage, a NAS) where she keeps bench files and pictures. Give the endpoint of "
          "each site, comma-separated with this site’s first; every one must hold the same bucket.",
    connected="Connected. She keeps files here from now on.",
    removed="Removed. She keeps no files unless the deployment’s own setup names a store.",
    holders=frozenset({"household"}), schemes=frozenset({"http", "https"}), address_placeholder="http://nas:9000",
    secret_field="token",
    secret_label='Bucket and keys as JSON: {"bucket": "…", "access_key": "…", "secret_key": "…"}',
    secret_noun="keys", check=check, ports=frozenset({"files"}), deployment=True, addresses=True,
    refusals={"bad_url": "Each endpoint is an http or https address, comma-separated",
              "key_refused": "The bucket and keys must be the JSON shown, and an endpoint turned the keys away",
              "unreachable": "An endpoint did not answer in time; try again shortly",
              "wrong_service": "An endpoint has no bucket of that name"})

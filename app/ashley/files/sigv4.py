"""AWS Signature Version 4 for a request with its whole body in hand: the `Authorization`, `x-amz-date` and
`x-amz-content-sha256` headers that S3-compatible storage requires. Pure; the clock is a parameter."""

import hashlib
import hmac
from datetime import datetime
from urllib.parse import quote

REGION = "us-east-1"
SERVICE = "s3"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode(), hashlib.sha256).digest()


def canonical_query(params: dict[str, str]) -> str:
    return "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(params.items()))


def sign(method: str, host: str, path: str, params: dict[str, str], body: bytes, access_key: str, secret_key: str,
         now: datetime) -> dict[str, str]:
    """The headers to send with `method` `path` (already percent-encoded, starting `/`) on `host` (as the `Host`
    header will be), `params` the query and `now` an aware UTC time."""
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    day = stamp[:8]
    payload = sha256_hex(body)
    headers = {"host": host, "x-amz-content-sha256": payload, "x-amz-date": stamp}
    names = ";".join(sorted(headers))
    canonical = "\n".join([method, path, canonical_query(params),
                           "".join(f"{k}:{headers[k]}\n" for k in sorted(headers)), names, payload])
    scope = f"{day}/{REGION}/{SERVICE}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope, sha256_hex(canonical.encode())])
    key = _hmac(_hmac(_hmac(_hmac(f"AWS4{secret_key}".encode(), day), REGION), SERVICE), "aws4_request")
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return {"x-amz-date": stamp, "x-amz-content-sha256": payload,
            "authorization": f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={names}, "
                             f"Signature={signature}"}

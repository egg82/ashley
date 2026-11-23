"""`/.well-known/assetlinks.json`, the Digital Asset Links statement that lets her Android app (`android/`) open this
site as a Trusted Web Activity, with no browser bar. It names the app's package and the SHA-256 fingerprint of the key
the app is signed with, the `android_key_sha256` setting. Unset, the route is 404 and the app still opens the site, as a
Custom Tab with a bar. Answered in place: a redirect fails the browser's check."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

PACKAGE = "io.github.egg82.ashley"
"""The app's package name, `applicationId` in `android/app/build.gradle`."""

router = APIRouter(include_in_schema=False)


def statement(fingerprint: str) -> list[dict[str, object]]:
    """The one statement: the app signed with `fingerprint` may handle every URL of this site."""
    return [{"relation": ["delegate_permission/common.handle_all_urls"],
             "target": {"namespace": "android_app", "package_name": PACKAGE,
                        "sha256_cert_fingerprints": [fingerprint]}}]


@router.get("/.well-known/assetlinks.json")
async def get_assetlinks(request: Request) -> Response:
    fingerprint: str = request.app.state.settings.android_key_sha256
    if not fingerprint:
        return Response(status_code=404)
    return JSONResponse(statement(fingerprint), media_type="application/json",
                        headers={"Cache-Control": "public, no-cache"})

"""What a kind asks of a new connection's label and catalogue provider beyond the request's schema
(`ConnectionKind.takes_label`, `ConnectionKind.picks_catalogue_provider`), checked by `ashley.api.connections` before
anything is sent to the service."""

from fastapi.responses import JSONResponse

from .. import services
from ..connections.kinds import ConnectionKind
from ..inference.catalogue import ModelCatalogue
from .models import ErrorResponse


def label_refused(kind: ConnectionKind, label: str) -> JSONResponse | None:
    """The 422 `bad_label` when `kind` does not take `label`; None when it does."""
    if kind.takes_label(label):
        return None
    return JSONResponse(status_code=422, content=ErrorResponse(
        code="bad_label", detail="that name is lowercase letters, digits, - and _, and not one a provider already has"
    ).model_dump())


async def catalogue_refused(kind: ConnectionKind, provider: str | None) -> JSONResponse | None:
    """The 422 `unsupported` when `provider` is named for a kind that takes none, or the model catalogue does not list
    it; None when it may be stored (or none was named)."""
    if provider is None:
        return None
    if not kind.picks_catalogue_provider:
        detail = f"{kind.title} is not priced from the model catalogue"
    else:
        catalogue = services.get(ModelCatalogue)
        await catalogue.refresh()
        if provider in catalogue.priced().merged.providers:
            return None
        detail = "the model catalogue lists no such provider"
    return JSONResponse(status_code=422, content=ErrorResponse(code="unsupported", detail=detail).model_dump())

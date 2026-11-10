"""A body that fails validation is answered 422 with FastAPI's `{"detail": [...]}` shape, minus what the error echoes:
its `input` is the offending value (for a missing field, the whole body, secrets included) and its `ctx` can carry
values too."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic_core import ErrorDetails


async def invalid_request(_: Request, exc: Exception) -> JSONResponse:
    errors: list[ErrorDetails] = list(exc.errors()) if isinstance(exc, RequestValidationError) else []
    detail = [{"type": error["type"], "loc": error["loc"], "msg": error["msg"]} for error in errors]
    return JSONResponse({"detail": detail}, status_code=422)

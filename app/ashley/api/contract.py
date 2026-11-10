"""What every route shares: readable operationIds, which become the generated client's method names."""

from fastapi.routing import APIRoute


def operation_id(route: APIRoute) -> str:
    """The route function's name (`get_health`), not FastAPI's path-derived default."""
    return route.name

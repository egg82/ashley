"""Awaiting a service from a test that holds a running TestClient."""

from collections.abc import Awaitable

from fastapi.testclient import TestClient


async def _await[T](awaitable: Awaitable[T]) -> T:
    return await awaitable


def on_app_loop[T](client: TestClient, awaitable: Awaitable[T]) -> T:
    """Awaits on the app's own event loop. The database pool wakes its waiters from that loop's thread, so a second loop
    (`asyncio.run`) awaiting the same pool sleeps until its next timer, production's 5 s connect timeout."""
    assert client.portal is not None
    return client.portal.call(_await, awaitable)

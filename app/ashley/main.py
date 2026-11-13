"""The app factory: `uvicorn ashley.main:create_app --factory`, port 8080."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from . import logs, services, settings as settings_module, wiring, wiring_singletons
from .api import (accounts, admin_gate, bench_files, bench_jobs, bench_runs, bench_talk, benches, chat, connection_holders, connection_oauth, connection_settings, connections, device_controls, devices, files, health, history, household, kiosk, lexicon, look, mail_bridge, mail_bridge_login,
                  kiosk_device, live, memory, messages, people, person, persona, push, ready, reminders, signin, skills, spend, spend_routes, spoken,
                  validation, voice_clips, voice_turns, wakes)
from .api.access import AccessLog
from .api.contract import operation_id
from .db.database import Database
from .web import legal
from .web.static import mount_client


def create_app(settings: settings_module.Settings | None = None, database: Database | None = None) -> FastAPI:
    """Wire the services and build the app; `settings` defaults to the environment's, and `database` to a pool over
    `settings.database_url` with production's timeouts."""
    settings = settings or settings_module.from_env()
    logs.setup()
    closers = wiring.wire(settings, database=database)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        database = services.get(Database)
        await database.open()
        running = [asyncio.create_task(job) for job in (*wiring.warmups(settings), *wiring_singletons.singletons(settings))]
        try:
            yield
        finally:
            for task in running:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            for close in closers:
                await close()
            await database.close()

    app = FastAPI(title="Ashley", version="1", lifespan=lifespan, generate_unique_id_function=operation_id,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.add_middleware(AccessLog)
    app.include_router(health.router)
    app.include_router(ready.router)
    app.include_router(messages.router)
    app.include_router(wakes.router)
    app.include_router(voice_clips.router)
    app.include_router(voice_turns.router)
    app.include_router(signin.router)
    app.include_router(memory.router)
    app.include_router(reminders.router)
    app.include_router(accounts.router)
    app.include_router(connections.router)
    app.include_router(connection_oauth.router)
    app.include_router(connection_holders.router)
    app.include_router(connection_settings.router)
    app.include_router(mail_bridge.router)
    app.include_router(mail_bridge_login.router)
    app.include_router(devices.router)
    app.include_router(device_controls.router)
    app.include_router(spend.router)
    app.include_router(spend_routes.router)
    app.include_router(lexicon.router)
    app.include_router(household.router)
    app.include_router(people.router)
    app.include_router(persona.router)
    app.include_router(chat.router)
    app.include_router(history.router)
    app.include_router(live.router)
    app.include_router(push.router)
    app.include_router(kiosk.router)
    app.include_router(spoken.router)
    app.include_router(benches.router)
    app.include_router(bench_talk.router)
    app.include_router(bench_runs.router)
    app.include_router(bench_jobs.router)
    app.include_router(bench_files.router)
    app.include_router(files.router)
    app.include_router(look.router)
    app.include_router(skills.router)
    app.include_router(legal.router)
    app.add_exception_handler(messages.Unauthorized, messages.unauthorized)
    app.add_exception_handler(messages.Unavailable, messages.unavailable)
    app.add_exception_handler(messages.RateLimited, messages.rate_limited)
    app.add_exception_handler(person.NotSignedIn, person.not_signed_in)
    app.add_exception_handler(person.CrossSite, person.cross_site)
    app.add_exception_handler(person.SessionsDown, person.sessions_down)
    app.add_exception_handler(admin_gate.NotAdmin, admin_gate.not_admin)
    app.add_exception_handler(kiosk_device.NotPaired, kiosk_device.not_paired)
    app.add_exception_handler(RequestValidationError, validation.invalid_request)
    mount_client(app)
    return app

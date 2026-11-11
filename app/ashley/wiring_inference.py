"""Wiring of inference: the router, the keyed providers and a household's route choices. Called by `ashley.wiring.wire`."""

from collections.abc import Callable, Coroutine
from functools import partial
from typing import Any

from . import services
from .connections.connections import Connections
from .db.database import Database
from .inference import image_quota, prices, routes as inference_routes
from .inference.balance import ProviderBalances
from .inference.balance_reader import SourcedBalances
from .inference.household_routes import HouseholdRoutes
from .inference.image_quota import ImageCap
from .inference.inference import Inference
from .inference.keyed_providers import KeyedProviders
from .inference.kinds import KEYED
from .inference.layered_routes import LayeredRoutes
from .inference.postgres import PostgresSpendLedger
from .inference.postgres_route_choice_write import PostgresRouteChoiceWriter
from .inference.postgres_route_choices import PostgresRouteChoices
from .inference.provider_keys import ConnectionProviderKeys
from .inference.route_choice_write import RouteChoiceWriter
from .inference.router import RoutedInference
from .inference.routes import Routes
from .settings import Settings
from .wiring_providers import env_keys, providers


def wire_inference(settings: Settings, narrow: Callable[[Routes], Routes],
                   closers: list[Callable[[], Coroutine[Any, Any, None]]]) -> None:
    """The router over the keyless providers and the keyed ones (`ashley.inference.kinds`), whose keys are the first
    household's connections where it has them and the env's elsewhere, read again every `REFRESH_S`; routes are
    checked against every provider a key could turn on, and a household's choices are laid over them. The spend page
    reads the keyed providers' balances and sets the household's choices."""
    wired, env, database = providers(settings), env_keys(settings), services.get(Database)
    keyed = KeyedProviders(KEYED, ConnectionProviderKeys(lambda: services.get(Connections), (k.kind.name for k in KEYED),
                                                         env), env)
    closers.append(keyed.close)
    checkers, keyless = {**keyed.checkers(), **{p.name: p for p in wired}}, frozenset(p.name for p in wired)
    routes = inference_routes.load(checkers, settings.routes_file)
    households = LayeredRoutes(inference_routes.deployment(settings.routes_file), checkers,
                               lambda: keyless | keyed.current().keys(), PostgresRouteChoices(database), narrow)
    services.register(HouseholdRoutes, households)
    services.register(RouteChoiceWriter, PostgresRouteChoiceWriter(database))
    services.register(Inference, RoutedInference(
        narrow(routes), wired, PostgresSpendLedger(database), prices.load(),
        image_cap=ImageCap(partial(image_quota.drawn, database), image_quota.load()), keyed=keyed,
        households=households))
    services.register(ProviderBalances, SourcedBalances(keyed.balance_sources))

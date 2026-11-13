"""Wiring of inference: the router, the keyed providers and a household's route choices. Called by `ashley.wiring.wire`."""

from collections.abc import Callable, Coroutine
from functools import partial
from typing import Any

from . import services
from .connections.connections import Connections
from .db.database import Database
from .inference import catalogue_config, catalogue_snapshot, compatible, image_quota, routes as inference_routes, wyoming_kind
from .inference.balance import ProviderBalances
from .inference.balance_reader import SourcedBalances
from .inference.catalogue import ModelCatalogue
from .inference.catalogue_override_write import CatalogueOverrideWriter
from .inference.household_routes import HouseholdRoutes
from .inference.image_quota import ImageCap
from .inference.inference import Inference
from .inference.keyed_providers import KeyedProviders
from .inference.kinds import KEYED
from .inference.layered_routes import LayeredRoutes
from .inference.postgres import PostgresSpendLedger
from .inference.postgres_catalogue import PostgresCatalogue
from .inference.postgres_catalogue_override_write import PostgresCatalogueOverrideWriter
from .inference.postgres_route_choice_write import PostgresRouteChoiceWriter
from .inference.postgres_route_choices import PostgresRouteChoices
from .inference.provider_keys import ConnectionProviderKeys
from .inference.route_choice_write import RouteChoiceWriter
from .inference.router import RoutedInference
from .inference.routes import Routes
from .inference.stored_catalogue import StoredCatalogue
from .settings import Settings
from .wiring_providers import env_addressed, env_compatible, env_keys, providers


def wire_inference(settings: Settings, narrow: Callable[[Routes], Routes],
                   closers: list[Callable[[], Coroutine[Any, Any, None]]]) -> None:
    """The router over the keyless providers, the keyed ones (`ashley.inference.kinds`), the OpenAI-compatible ones
    (`ashley.inference.compatible`) and Wyoming (`ashley.inference.wyoming_kind`), whose keys and addresses are the first
    household's connections where it has them and the env's elsewhere, read again every `REFRESH_S`; routes are
    checked against every provider a key could turn on, and a household's choices are laid over them. The spend page
    reads the keyed providers' balances and sets the household's choices. The model catalogue prices every call from
    the image's snapshot, the stored fetch and a person's overrides (`ashley.inference.stored_catalogue`)."""
    wired, env, database = providers(settings), env_keys(settings), services.get(Database)
    local, addressed = env_compatible(settings), env_addressed(settings)
    keys = ConnectionProviderKeys(lambda: services.get(Connections), (k.kind.name for k in KEYED), env,
                                  compatible.NAME, local, (wyoming_kind.NAME,), addressed)
    keyed = KeyedProviders(KEYED, keys, env, compatible=compatible.build, compatible_env=local,
                           addressed=(wyoming_kind.PROVIDER,), addressed_env=addressed)
    closers.append(keyed.close)
    checkers, keyless = {**keyed.checkers(), **{p.name: p for p in wired}}, frozenset(p.name for p in wired)
    routes = inference_routes.load(checkers, settings.routes_file)
    households = LayeredRoutes(inference_routes.deployment(settings.routes_file), checkers,
                               lambda: keyless | keyed.current().keys(), PostgresRouteChoices(database), narrow)
    services.register(HouseholdRoutes, households)
    services.register(RouteChoiceWriter, PostgresRouteChoiceWriter(database))
    catalogue = StoredCatalogue(catalogue_snapshot.load(), PostgresCatalogue(database), catalogue_config.load())
    services.register(ModelCatalogue, catalogue)
    services.register(CatalogueOverrideWriter, PostgresCatalogueOverrideWriter(database))
    services.register(Inference, RoutedInference(
        narrow(routes), wired, PostgresSpendLedger(database), catalogue,
        image_cap=ImageCap(partial(image_quota.drawn, database), image_quota.load()), keyed=keyed,
        households=households))
    services.register(ProviderBalances, SourcedBalances(keyed.balance_sources))

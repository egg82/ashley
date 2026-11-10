"""The wire models of the Usage room's model choices (`ashley.api.spend_routes`, `api-contract-first`): which model
carries each chat-facing task for the signed-in person's household, and what it may choose instead."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..inference.model import Task


class RouteModel(BaseModel):
    """One route: the provider (its name in the routes data, as the Usage room's provider rows name it) and the model
    id it calls."""

    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=200)


class TaskRoutes(BaseModel):
    """One task. `household`: whether this household may choose its model; false for `action_judge`, which is shown so a
    person can see which model judges a change, and only the operator moves. `routes`: the deployment's routes, in the
    order a call tries them. `chosen`: the household's choice, tried before `routes`; null when it has none.
    `options`: what it may choose now (the deployment's routes for its chat-facing tasks whose provider is wired), in
    order; empty when `household` is false."""

    task: Task
    household: bool
    routes: list[RouteModel]
    chosen: RouteModel | None
    options: list[RouteModel]


class SpendRoutesResponse(BaseModel):
    """`choices`: every task the household may choose for, in task order, then `action_judge`. A choice reaches every
    reply within `refresh_s` seconds."""

    choices: list[TaskRoutes]
    refresh_s: int


class SpendRouteRequest(BaseModel):
    """The model for one task, or null to go back to the deployment's routes."""

    model_config = ConfigDict(extra="forbid")

    route: RouteModel | None


class SpendRouteRefused(BaseModel):
    """Why nothing was stored: `not_household` (the task is not one a household chooses for), `not_offered` (not one of
    its options), `unwired` (an option whose provider has no key now)."""

    reason: Literal["not_household", "not_offered", "unwired"]
    detail: str

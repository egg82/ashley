"""The wire models of a person: who is signed in (`ashley.api.signin`), the people routes (`ashley.api.people`), and the
`Person` every other route serves."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from ..people import model


class Person(BaseModel):
    """One person of a household, as they are known to her. `name` is theirs to see; it is never logged. `admin` is
    whether they may change what the whole deployment shares (a model provider's key, who else is an admin); the
    server checks it on every such change, so a client uses it only to show or hide those actions."""

    id: int
    household_id: int
    name: str
    admin: bool


def wire_person(p: model.Person) -> Person:
    """A person as every route serves one."""
    return Person(id=p.id, household_id=p.household_id, name=p.name, admin=p.admin)


class MeResponse(BaseModel):
    """Who this browser is signed in as."""

    person: Person


class PeopleResponse(BaseModel):
    """The signed-in person's household's people, ordered by id, each with whether they are an admin now.
    `admins_from` says who decides that: `app`, an admin here (`PUT /api/people/{id}/admin`); `provider`, the sign-in
    provider's admin group alone (`ADMIN_GROUP`), read at each sign-in, and nobody grants or revokes here. Under
    `provider`, a person is an admin now while a live session of theirs was opened by a sign-in the group named them
    in."""

    people: list[Person]
    admins_from: Literal["app", "provider"]


class AdminRequest(BaseModel):
    """Whether the person is to be an admin of the deployment."""

    model_config = ConfigDict(extra="forbid")

    admin: bool

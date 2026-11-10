"""Wiring of the skills and of the persona overrides kept in their changelog. Called by `ashley.wiring.wire`."""

from . import services
from .db.database import Database
from .persona import sections
from .skills import config, seeds
from .skills.persona import PersonaOverrides
from .skills.persona_write import PersonaWriter
from .skills.postgres import PostgresSkills
from .skills.postgres_persona import PostgresPersonaOverrides
from .skills.postgres_persona_write import PostgresPersonaWriter
from .skills.skills import Skills


def wire_skills() -> None:
    """Register `Skills`, `PersonaOverrides` and `PersonaWriter`, the writer taking only the shipped persona's
    `allowed` sections."""
    database, loaded = services.get(Database), config.load()
    services.register(Skills, PostgresSkills(database, loaded, seeds.load(loaded)))
    services.register(PersonaOverrides, PostgresPersonaOverrides(database, loaded))
    shipped = {s.id: s.body for s in sections.catalogue()}
    services.register(PersonaWriter, PostgresPersonaWriter(database, loaded, shipped))

"""Voiceprints: the vectors enrolled for a household's people, each with the model that made it and the device it was
enrolled on, and the devices armed to enrol someone from their next wakes. A vector's length is the model's, so the
column has no fixed dimension; prints are compared in the app, never indexed. Removing a person removes their prints
and any enrolment armed for them. An enrolment is deleted when its last wake is used or it is found expired."""

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE voiceprints (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            household_id bigint NOT NULL,
            person_id bigint NOT NULL,
            model text NOT NULL CHECK (model ~ '\S'),
            vector vector NOT NULL CHECK (vector_dims(vector) > 0),
            device_id bigint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (person_id, household_id) REFERENCES people (id, household_id) ON DELETE CASCADE,
            FOREIGN KEY (device_id, household_id) REFERENCES devices (id, household_id)
        );

        CREATE INDEX voiceprints_by_household_model ON voiceprints (household_id, model, person_id);
        CREATE INDEX voiceprints_by_person ON voiceprints (person_id);

        CREATE TABLE voice_enrolments (
            device_id bigint PRIMARY KEY,
            household_id bigint NOT NULL,
            person_id bigint NOT NULL,
            remaining integer NOT NULL CHECK (remaining >= 0),
            until timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (person_id, household_id) REFERENCES people (id, household_id) ON DELETE CASCADE,
            FOREIGN KEY (device_id, household_id) REFERENCES devices (id, household_id) ON DELETE CASCADE
        );

        CREATE INDEX voice_enrolments_by_person ON voice_enrolments (person_id);
        """
    )

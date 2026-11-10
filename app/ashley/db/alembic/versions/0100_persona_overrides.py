"""A household's overrides of the persona's overridable sections, as a second family in the skills' changelog:
`family` `persona` rows carry a section id in `kind`, are always a person's and live, and a null body means "back to
the shipped text". Every existing row is a skill."""

from alembic import op

revision: str = "0100"
down_revision: str | None = "0099"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE skill_versions ADD COLUMN family text NOT NULL DEFAULT 'skill'
            CHECK (family IN ('skill', 'persona'));
        ALTER TABLE skill_versions ALTER COLUMN family DROP DEFAULT;
        ALTER TABLE skill_versions DROP CONSTRAINT skill_versions_pkey;
        ALTER TABLE skill_versions ADD PRIMARY KEY (household_id, family, kind, version);
        ALTER TABLE skill_versions ALTER COLUMN body DROP NOT NULL;
        ALTER TABLE skill_versions ADD CONSTRAINT skill_versions_skill_body CHECK (family = 'persona' OR body IS NOT NULL);
        ALTER TABLE skill_versions ADD CONSTRAINT skill_versions_persona_by_a_person
            CHECK (family = 'skill' OR (status = 'live' AND person_id IS NOT NULL AND bench_id IS NULL));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM skill_versions WHERE family = 'persona';
        ALTER TABLE skill_versions DROP CONSTRAINT skill_versions_persona_by_a_person;
        ALTER TABLE skill_versions DROP CONSTRAINT skill_versions_skill_body;
        ALTER TABLE skill_versions ALTER COLUMN body SET NOT NULL;
        ALTER TABLE skill_versions DROP CONSTRAINT skill_versions_pkey;
        ALTER TABLE skill_versions ADD PRIMARY KEY (household_id, kind, version);
        ALTER TABLE skill_versions DROP COLUMN family;
        """
    )

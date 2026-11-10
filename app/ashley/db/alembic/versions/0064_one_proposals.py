"""Her proposals are one table: `proposals` holds what she proposed to a person for their OK as a JSON object tagged by
kind (`ashley.senses.proposal_payloads`), per topic (`reminder`, `house`), and takes the rows of `deposit_proposals` and
`house_proposals`, which are dropped. Downgrade restores both."""

from alembic import op

revision: str = "0064"
down_revision: str | None = "0063"

_UTC = r"""'YYYY-MM-DD"T"HH24\:MI\:SS.US"+00\:00"'"""


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE proposals (
            id bigserial PRIMARY KEY,
            household_id bigint NOT NULL REFERENCES households (id) ON DELETE CASCADE,
            made_by bigint NOT NULL,
            conversation_id bigint NOT NULL,
            turn_id bigint NOT NULL,
            topic text NOT NULL,
            payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX proposals_slot ON proposals (made_by, conversation_id, topic, id);
        CREATE INDEX proposals_age ON proposals (topic, created_at);

        INSERT INTO proposals (household_id, made_by, conversation_id, turn_id, topic, payload, created_at)
        SELECT household_id, made_by, conversation_id, turn_id, 'reminder',
               jsonb_build_object(
                   'kind', CASE WHEN rule IS NOT NULL THEN 'money_rule' WHEN target IS NOT NULL THEN 'reminder_change'
                                ELSE 'reminder' END,
                   'reminder', jsonb_build_object(
                       'household_id', household_id, 'person_id', person_id, 'made_by', made_by, 'brief', brief,
                       'due_at', to_char(COALESCE(due_at, created_at) AT TIME ZONE 'UTC', {_UTC}),
                       'repeat', repeat, 'route', route, 'tools', to_jsonb(tools)))
               || CASE WHEN rule IS NOT NULL THEN jsonb_build_object('rule', rule) ELSE '{{}}'::jsonb END
               || CASE WHEN target IS NOT NULL THEN jsonb_build_object('target', target) ELSE '{{}}'::jsonb END,
               created_at
        FROM deposit_proposals ORDER BY id;

        INSERT INTO proposals (household_id, made_by, conversation_id, turn_id, topic, payload, created_at)
        SELECT household_id, made_by, conversation_id, turn_id, 'house',
               jsonb_build_object('kind', 'house_change', 'summary', summary, 'change', change), created_at
        FROM house_proposals ORDER BY id;

        DROP TABLE deposit_proposals;
        DROP TABLE house_proposals;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE deposit_proposals (
            id bigserial PRIMARY KEY,
            household_id bigint NOT NULL REFERENCES households (id) ON DELETE CASCADE,
            person_id bigint NOT NULL,
            made_by bigint NOT NULL,
            conversation_id bigint NOT NULL,
            turn_id bigint NOT NULL,
            brief text NOT NULL,
            rule jsonb CHECK (jsonb_typeof(rule) = 'object'),
            created_at timestamptz NOT NULL DEFAULT now(),
            due_at timestamptz,
            repeat jsonb CHECK (jsonb_typeof(repeat) = 'object'),
            route text NOT NULL DEFAULT 'phone' CHECK (route IN ('phone', 'quiet')),
            tools text[],
            target bigint
        );
        CREATE INDEX deposit_proposals_age ON deposit_proposals (created_at);
        CREATE TABLE house_proposals (
            id bigserial PRIMARY KEY,
            household_id bigint NOT NULL REFERENCES households (id) ON DELETE CASCADE,
            made_by bigint NOT NULL,
            conversation_id bigint NOT NULL,
            turn_id bigint NOT NULL,
            change jsonb NOT NULL CHECK (jsonb_typeof(change) = 'object'),
            summary text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX house_proposals_age ON house_proposals (created_at);

        INSERT INTO deposit_proposals (household_id, person_id, made_by, conversation_id, turn_id, brief, rule, created_at,
                                       due_at, repeat, route, tools, target)
        SELECT household_id, (payload #>> '{reminder,person_id}')::bigint, made_by, conversation_id, turn_id,
               payload #>> '{reminder,brief}', payload -> 'rule', created_at,
               (payload #>> '{reminder,due_at}')::timestamptz,
               CASE WHEN jsonb_typeof(payload #> '{reminder,repeat}') = 'object' THEN payload #> '{reminder,repeat}' END,
               payload #>> '{reminder,route}',
               CASE WHEN jsonb_typeof(payload #> '{reminder,tools}') = 'array'
                    THEN ARRAY(SELECT jsonb_array_elements_text(payload #> '{reminder,tools}')) END,
               (payload ->> 'target')::bigint
        FROM proposals WHERE topic = 'reminder' ORDER BY id;

        INSERT INTO house_proposals (household_id, made_by, conversation_id, turn_id, change, summary, created_at)
        SELECT household_id, made_by, conversation_id, turn_id, payload -> 'change', payload ->> 'summary', created_at
        FROM proposals WHERE topic = 'house' ORDER BY id;

        DROP TABLE proposals;
        """
    )

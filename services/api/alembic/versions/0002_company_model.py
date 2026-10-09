"""Company model: the tenant's customers, engagements, and the frameworks they demand.

Migration 0001 modelled *our* tenant and the agents inside it. That is only half the
picture, and the missing half is the reason the product exists.

An organisation does not seek accreditation in the abstract. It seeks approval from a
named client, under that client's chosen framework, for a specific version of an agent,
within that client's residency envelope, against that client's service-level terms. The
same agent may be approved at v2.4 for one client and pinned at v2.1 for another who has
not re-reviewed. Two clients asking the identical question in different formats is the
single most expensive repeated cost this platform removes.

None of that is expressible without a customer dimension, so this migration adds it:

    organizations  (tenant — the party that pays us)
      └── customers  (their clients — the party that must approve)
            ├── customer_contacts        who reviews, who signs
            ├── customer_frameworks      what evidence they demand
            └── engagements              a delivery, with terms
                  ├── engagement_service_levels
                  └── engagement_agents  which agents, at which approved version

    frameworks  (reference data; org_id NULL means shipped by us)
      └── framework_controls
            └── control_mappings         which of our evidence answers this control

Hand-written per AGENTS.md rule 7.

Revision ID: 0002_company_model
Revises: 0001_baseline
Create Date: 2026-09-13
"""

from __future__ import annotations

from alembic import op

revision = "0002_company_model"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


# Tables that carry a hard org_id and are isolated per tenant.
TENANT_TABLES = (
    "customers",
    "customer_contacts",
    "customer_frameworks",
    "engagements",
    "engagement_service_levels",
    "engagement_agents",
)

# Tables where org_id IS NULL means "reference data we ship". Every tenant reads those
# rows; no tenant may write them. A tenant's own rows behave normally.
REFERENCE_TABLES = (
    "frameworks",
    "framework_controls",
    "control_mappings",
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Shared helper. 0001 declared updated_at columns but left them to the
    # application. A trigger is the same behaviour with one fewer thing to
    # forget, so it is introduced here and applied to agents as well.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER agents_touch_updated_at
            BEFORE UPDATE ON agents
            FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
    """)

    # ------------------------------------------------------------------
    # Enums
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TYPE customer_status AS ENUM
            ('prospect','active','suspended','offboarding','churned');

        -- How much rigour this client's review demands. Drives default framework
        -- selection, probe frequency and whether conditional accreditation is allowed.
        CREATE TYPE criticality_tier AS ENUM ('tier_1','tier_2','tier_3');

        CREATE TYPE engagement_state AS ENUM
            ('draft','active','suspended','terminated');

        CREATE TYPE contact_role AS ENUM
            ('security_reviewer','data_protection','business_owner',
             'procurement','technical','executive_sponsor');

        CREATE TYPE framework_kind AS ENUM
            ('standard','regulation','certification','questionnaire','internal_policy');

        CREATE TYPE requirement_level AS ENUM ('mandatory','expected','informational');

        -- How completely one piece of our evidence answers one control. Reviewers
        -- distrust a pack that claims full satisfaction everywhere, so the distinction
        -- is modelled rather than flattened.
        CREATE TYPE mapping_strength AS ENUM
            ('satisfies','partially_satisfies','supports');

        -- Whether a client accepts new agent versions automatically or requires review.
        CREATE TYPE version_uptake AS ENUM
            ('pinned','auto_patch','auto_minor','auto_all');
    """)

    # ==================================================================
    # CUSTOMERS — the tenant's clients
    # ==================================================================
    op.execute("""
        CREATE TABLE customers (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id        uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

            slug          text NOT NULL,
            -- legal_name is what appears on an accreditation pack; display_name is what
            -- appears in the console. They differ more often than not.
            legal_name    text NOT NULL,
            display_name  text NOT NULL,

            status        customer_status NOT NULL DEFAULT 'prospect',

            -- Sector is constrained rather than free text because it selects the default
            -- framework set. A bank and a hospital demand different evidence.
            sector        text,

            -- Residency evaluation starts here. home_jurisdiction is ISO 3166-1 alpha-2.
            home_jurisdiction       text,
            operating_jurisdictions text[] NOT NULL DEFAULT '{}',

            criticality   criticality_tier NOT NULL DEFAULT 'tier_2',

            -- Reconciliation with whatever CRM or contract system already holds this client.
            external_ref  text,
            notes         text,

            created_at    timestamptz NOT NULL DEFAULT now(),
            updated_at    timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT customers_slug_unique UNIQUE (org_id, slug),
            CONSTRAINT customers_sector_valid CHECK (
                sector IS NULL OR sector IN (
                    'financial_services','insurance','healthcare','life_sciences',
                    'public_sector','defence','telecom','energy','utilities',
                    'retail','manufacturing','transport','technology','education','other'
                )
            ),
            CONSTRAINT customers_home_jurisdiction_valid CHECK (
                home_jurisdiction IS NULL OR home_jurisdiction ~ '^[A-Z]{2}$'
            )
        );

        CREATE INDEX customers_org_status_idx ON customers (org_id, status);
        CREATE INDEX customers_org_sector_idx ON customers (org_id, sector);
        CREATE INDEX customers_criticality_idx
            ON customers (org_id, criticality) WHERE status = 'active';

        CREATE TRIGGER customers_touch_updated_at
            BEFORE UPDATE ON customers
            FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
    """)

    # ------------------------------------------------------------------
    # Contacts. Validity windows mirror agent_ownership so accountability
    # survives a reorg on the client side too.
    #
    # Deliberately minimal: a principal reference and a display name, nothing
    # more. This table holds the only personal data in the schema, so it is
    # kept separable and purgeable on its own.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE customer_contacts (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id       uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            customer_id  uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,

            role         contact_role NOT NULL,
            principal_id text NOT NULL,
            display_name text,

            valid_from   timestamptz NOT NULL DEFAULT now(),
            valid_to     timestamptz,

            CONSTRAINT contact_window_sane CHECK (valid_to IS NULL OR valid_to > valid_from)
        );

        -- At most one current holder per role per customer.
        CREATE UNIQUE INDEX customer_contacts_current_idx
            ON customer_contacts (customer_id, role) WHERE valid_to IS NULL;

        CREATE INDEX customer_contacts_principal_idx
            ON customer_contacts (org_id, principal_id) WHERE valid_to IS NULL;
    """)

    # ==================================================================
    # FRAMEWORKS — reference data, plus tenant-authored questionnaires
    #
    # org_id IS NULL means we ship it: ISO 42001, NIST AI RMF, the EU AI Act.
    # org_id set means a tenant added it, which is almost always a specific
    # client's bespoke security questionnaire.
    # ==================================================================
    op.execute("""
        CREATE TABLE frameworks (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id      uuid REFERENCES organizations(id) ON DELETE CASCADE,

            slug        text NOT NULL,
            name        text NOT NULL,
            kind        framework_kind NOT NULL,
            publisher   text,
            version     text,

            -- Used to suggest a default framework set from a customer's sector and
            -- jurisdiction rather than making someone pick from a list of forty.
            typical_sectors text[] NOT NULL DEFAULT '{}',
            jurisdictions   text[] NOT NULL DEFAULT '{}',

            source_url  text,
            created_at  timestamptz NOT NULL DEFAULT now(),

            -- Enables the composite foreign keys below, which keep a framework and its
            -- controls from ever landing in different tenants.
            CONSTRAINT frameworks_id_org_unique UNIQUE (id, org_id)
        );

        CREATE UNIQUE INDEX frameworks_builtin_slug_idx
            ON frameworks (slug) WHERE org_id IS NULL;
        CREATE UNIQUE INDEX frameworks_tenant_slug_idx
            ON frameworks (org_id, slug) WHERE org_id IS NOT NULL;
        CREATE INDEX frameworks_kind_idx ON frameworks (kind);
    """)

    op.execute("""
        CREATE TABLE framework_controls (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            framework_id uuid NOT NULL,
            -- Denormalised from the parent so row-level security needs no join.
            org_id       uuid,

            -- The client's own reference: 'A.6.2.2', 'GOVERN 1.1', 'Article 12', 'Q-47'.
            -- Reviewers navigate by this string, so it is stored exactly as published.
            control_ref  text NOT NULL,
            title        text NOT NULL,
            requirement  text,

            -- Grouping and ordering for pack rendering.
            section      text,
            ordinal      integer NOT NULL DEFAULT 0,

            -- Can this be answered from evidence, or does it need a written narrative?
            answer_mode  text NOT NULL DEFAULT 'evidence',

            -- Guard against shipping paraphrased regulatory text into a client-facing
            -- document. Seeded rows are 'paraphrased' and the pack renderer must refuse
            -- to quote them verbatim until someone has reviewed the wording. See Q-001.
            text_status  text NOT NULL DEFAULT 'paraphrased',

            CONSTRAINT framework_controls_ref_unique UNIQUE (framework_id, control_ref),
            CONSTRAINT framework_controls_parent_fk
                FOREIGN KEY (framework_id, org_id)
                REFERENCES frameworks (id, org_id) ON DELETE CASCADE,
            CONSTRAINT framework_controls_answer_mode_valid CHECK (
                answer_mode IN ('evidence','narrative','hybrid','not_applicable')
            ),
            CONSTRAINT framework_controls_text_status_valid CHECK (
                text_status IN ('paraphrased','reviewed','verbatim_licensed')
            )
        );

        CREATE INDEX framework_controls_framework_idx
            ON framework_controls (framework_id, section, ordinal);
    """)

    # ------------------------------------------------------------------
    # Control mappings. This is the table that turns "every client asks for the
    # same evidence in a different format" from recurring work into a lookup.
    #
    # Evidence is produced once. A mapping says which control in which framework
    # that evidence answers, and how completely. Adding a client's bespoke
    # questionnaire becomes mapping rows, not a new evidence pipeline.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE control_mappings (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            control_id    uuid NOT NULL REFERENCES framework_controls(id) ON DELETE CASCADE,
            org_id        uuid REFERENCES organizations(id) ON DELETE CASCADE,

            -- Which kind of evidence this platform produces. Constrained because a typo
            -- here yields a pack with a silently empty answer, which is worse than an error.
            evidence_kind text NOT NULL,
            strength      mapping_strength NOT NULL DEFAULT 'satisfies',

            -- Identifier of the query or rule that materialises the evidence. Resolved
            -- by the accreditation module against a registry of named producers.
            producer      text NOT NULL,

            -- Sentence rendered above the evidence in the pack. Placeholders are filled
            -- from the agent version and engagement.
            narrative_template text,

            created_at    timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT control_mappings_unique
                UNIQUE NULLS NOT DISTINCT (control_id, evidence_kind, org_id),
            CONSTRAINT control_mappings_evidence_kind_valid CHECK (
                evidence_kind IN (
                    'bom_completeness','model_inventory','tool_permission_inventory',
                    'data_class_inventory','residency_proof','redaction_record',
                    'approval_record','ownership_record','oversight_record',
                    'change_history','materiality_verdict',
                    'vulnerability_scan','adversarial_probe',
                    'service_level_attainment','chain_integrity','incident_record'
                )
            )
        );

        CREATE INDEX control_mappings_control_idx ON control_mappings (control_id);
        CREATE INDEX control_mappings_kind_idx ON control_mappings (evidence_kind);
    """)

    # ------------------------------------------------------------------
    # What a given client demands. Held at customer level rather than per
    # engagement: in practice a client's security baseline applies across every
    # delivery. See Q-002 before adding an engagement override.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE customer_frameworks (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id         uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            customer_id    uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            framework_id   uuid NOT NULL REFERENCES frameworks(id) ON DELETE RESTRICT,

            level          requirement_level NOT NULL DEFAULT 'mandatory',

            -- Empty means the whole framework. Clients frequently scope to a subset,
            -- and producing answers for controls nobody asked about wastes review time.
            scoped_controls text[] NOT NULL DEFAULT '{}',

            required_since date,
            notes          text,

            created_at     timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT customer_frameworks_unique UNIQUE (customer_id, framework_id)
        );

        CREATE INDEX customer_frameworks_customer_idx ON customer_frameworks (customer_id);
        CREATE INDEX customer_frameworks_framework_idx ON customer_frameworks (org_id, framework_id);
    """)

    # ==================================================================
    # ENGAGEMENTS — a delivery to a client, with its terms
    # ==================================================================
    op.execute("""
        CREATE TABLE engagements (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id       uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            customer_id  uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,

            slug         text NOT NULL,
            name         text NOT NULL,
            description  text,
            state        engagement_state NOT NULL DEFAULT 'draft',

            -- Residency envelope. Every agent delivered under this engagement is
            -- evaluated against these, and an observed region outside them is a
            -- reportable policy breach rather than a warning.
            permitted_regions     text[] NOT NULL DEFAULT '{}',
            prohibited_regions    text[] NOT NULL DEFAULT '{}',
            cross_border_transfer text NOT NULL DEFAULT 'prohibited',
            permitted_data_classes text[] NOT NULL DEFAULT '{}',

            -- Commercial envelope.
            contract_ref text,
            starts_on    date,
            ends_on      date,

            -- Approver of record on each side. The client-side name is what makes an
            -- accreditation defensible, so it is a first-class column.
            delivery_lead     text,
            customer_approver text,

            created_at   timestamptz NOT NULL DEFAULT now(),
            updated_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT engagements_slug_unique UNIQUE (org_id, customer_id, slug),
            CONSTRAINT engagements_dates_sane CHECK (
                ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on
            ),
            -- Three rungs as originally shipped. `permitted_with_consent` is added by
            -- 0006, not here, and this list must stay as it is: a database that has
            -- already run this revision will never see an edit to it, so widening the
            -- constraint in place produced two different schemas both reporting the
            -- same revision. See Q-011 and D-031.
            CONSTRAINT engagements_cross_border_valid CHECK (
                cross_border_transfer IN
                    ('prohibited','permitted_with_safeguards','permitted')
            ),
            -- A region cannot be both allowed and forbidden. Caught here because the
            -- consequence downstream is a policy engine that silently picks one.
            CONSTRAINT engagements_regions_disjoint CHECK (
                NOT (permitted_regions && prohibited_regions)
            )
        );

        CREATE INDEX engagements_customer_idx ON engagements (customer_id, state);
        CREATE INDEX engagements_org_state_idx ON engagements (org_id, state);

        CREATE TRIGGER engagements_touch_updated_at
            BEFORE UPDATE ON engagements
            FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
    """)

    # ------------------------------------------------------------------
    # Service levels. Shape matches the service_levels block in the AAP
    # descriptor so a commitment and its measurement are the same structure.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE engagement_service_levels (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id        uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            engagement_id uuid NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,

            kind          text NOT NULL,
            target        numeric NOT NULL,
            unit          text,
            -- Not `window`: that is a reserved word in Postgres and would have to be
            -- quoted in every raw statement that touches it. See D-018.
            measurement_window text NOT NULL DEFAULT 'monthly',

            -- An unmeasured penalty is a contractual claim, not a commitment. Recording
            -- the basis is what lets the SLA engine attach consequence to a breach.
            penalty_basis  text NOT NULL DEFAULT 'none',
            penalty_detail text,

            created_at    timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT esl_unique UNIQUE (engagement_id, kind, measurement_window),
            CONSTRAINT esl_kind_valid CHECK (
                kind IN ('availability','latency_p95','latency_p99','error_rate',
                         'resolution_p1','resolution_p2','freshness','throughput')
            ),
            CONSTRAINT esl_window_valid CHECK (
                measurement_window IN ('daily','weekly','monthly','quarterly','annual')
            ),
            CONSTRAINT esl_penalty_valid CHECK (
                penalty_basis IN ('none','service_credit','fee_reduction','termination_right')
            )
        );

        CREATE INDEX esl_engagement_idx ON engagement_service_levels (engagement_id);
    """)

    # ------------------------------------------------------------------
    # Which agents are in scope, and critically, at which version *for this
    # client*.
    #
    # agents.current_version_id is what is running. This table records what a
    # specific client actually approved, which is frequently older. A client who
    # has not re-reviewed since v2.1 is not covered for v2.4, and the difference
    # between those two columns is the single most important number in the
    # product: it is the accreditation drift.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE engagement_agents (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id        uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            engagement_id uuid NOT NULL REFERENCES engagements(id) ON DELETE CASCADE,
            agent_id      uuid NOT NULL REFERENCES agents(id) ON DELETE CASCADE,

            -- The version this client signed off. Null until first accreditation.
            accredited_version_id uuid REFERENCES agent_versions(id),
            -- The version actually serving this client right now.
            deployed_version_id   uuid REFERENCES agent_versions(id),

            -- Whether new versions may reach this client without a fresh review.
            uptake        version_uptake NOT NULL DEFAULT 'pinned',

            in_scope_since timestamptz NOT NULL DEFAULT now(),
            removed_at     timestamptz,

            CONSTRAINT engagement_agents_window_sane CHECK (
                removed_at IS NULL OR removed_at > in_scope_since
            )
        );

        -- One live row per agent per engagement; re-adding after removal is allowed.
        CREATE UNIQUE INDEX engagement_agents_live_idx
            ON engagement_agents (engagement_id, agent_id) WHERE removed_at IS NULL;

        CREATE INDEX engagement_agents_agent_idx
            ON engagement_agents (agent_id) WHERE removed_at IS NULL;

        -- The drift query: delivered something other than what was approved.
        CREATE INDEX engagement_agents_drift_idx
            ON engagement_agents (org_id)
            WHERE removed_at IS NULL
              AND deployed_version_id IS DISTINCT FROM accredited_version_id;
    """)

    # ------------------------------------------------------------------
    # Row-level security. A backstop; every query still filters by org_id.
    # ------------------------------------------------------------------
    for table in TENANT_TABLES:
        op.execute(f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (current_org_matches(org_id))
                WITH CHECK (current_org_matches(org_id));
        """)

    # Reference data: readable by everyone, writable only within your own tenant.
    # The asymmetry between USING and WITH CHECK is the whole point — it makes it
    # structurally impossible for a tenant to edit a shipped framework.
    for table in REFERENCE_TABLES:
        op.execute(f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY {table}_reference_read ON {table}
                FOR SELECT
                USING (org_id IS NULL OR current_org_matches(org_id));
            CREATE POLICY {table}_tenant_write ON {table}
                FOR ALL
                USING (current_org_matches(org_id))
                WITH CHECK (current_org_matches(org_id));
        """)

    _seed_frameworks()


def _seed_frameworks() -> None:
    """Ship the frameworks every enterprise client asks about.

    Control titles here are paraphrased summaries, not quoted text: ISO and the AICPA
    licence their wording, and quoting a regulation inexactly in a compliance document
    is its own liability. Every seeded row is therefore marked text_status =
    'paraphrased', and the pack renderer must refuse to present those verbatim to a
    client until a reviewer has replaced the wording. Tracked as Q-001.

    Control references themselves are real and are what reviewers navigate by.
    """
    op.execute("""
        INSERT INTO frameworks (org_id, slug, name, kind, publisher, version,
                                typical_sectors, jurisdictions, source_url)
        VALUES
            (NULL, 'iso-42001', 'ISO/IEC 42001:2023 — AI management systems',
             'standard', 'ISO/IEC', '2023',
             '{financial_services,insurance,healthcare,public_sector,telecom,technology}',
             '{}', 'https://www.iso.org/standard/81230.html'),

            (NULL, 'nist-ai-rmf', 'NIST AI Risk Management Framework 1.0',
             'standard', 'NIST', '1.0',
             '{financial_services,healthcare,public_sector,defence,technology}',
             '{US}', 'https://www.nist.gov/itl/ai-risk-management-framework'),

            (NULL, 'eu-ai-act', 'EU AI Act — high-risk system obligations',
             'regulation', 'European Union', '2024/1689',
             '{financial_services,insurance,healthcare,public_sector,education}',
             '{EU}', 'https://eur-lex.europa.eu/eli/reg/2024/1689/oj'),

            (NULL, 'soc2-trust', 'SOC 2 — Trust Services Criteria',
             'certification', 'AICPA', '2017 (rev. 2022)',
             '{technology,financial_services,healthcare}',
             '{US}', 'https://www.aicpa-cima.com');
    """)

    # ISO/IEC 42001 — Annex A controls most often cited in an agent review.
    op.execute("""
        INSERT INTO framework_controls
            (framework_id, org_id, control_ref, title, requirement, section, ordinal, answer_mode)
        SELECT f.id, NULL, c.control_ref, c.title, c.requirement, c.section, c.ordinal, c.answer_mode
        FROM frameworks f, (VALUES
            ('A.2.2',   'AI policy',
             'An organisational policy for the development and use of AI systems exists and is maintained.',
             'Policies', 10, 'narrative'),
            ('A.3.2',   'AI roles and responsibilities',
             'Responsibilities for AI systems are allocated to named roles and kept current.',
             'Organisation', 20, 'evidence'),
            ('A.5.2',   'AI system impact assessment',
             'Potential consequences of the AI system for individuals and groups are assessed and recorded.',
             'Impact', 30, 'hybrid'),
            ('A.6.2.2', 'AI system requirements and specification',
             'Requirements for the AI system, including its intended purpose and constraints, are documented.',
             'Life cycle', 40, 'evidence'),
            ('A.6.2.4', 'AI system verification and validation',
             'The AI system is verified and validated against its stated requirements before use.',
             'Life cycle', 50, 'evidence'),
            ('A.6.2.6', 'AI system operation and monitoring',
             'The AI system is monitored in operation and deviations are addressed.',
             'Life cycle', 60, 'evidence'),
            ('A.7.2',   'Data for development and enhancement',
             'Data used by the AI system is identified, and its provenance and suitability recorded.',
             'Data', 70, 'evidence'),
            ('A.9.2',   'Processes for responsible use',
             'Processes governing responsible use of the AI system are defined and followed.',
             'Use', 80, 'hybrid'),
            ('A.10.2',  'Allocating responsibilities in the AI value chain',
             'Responsibilities between the organisation and its suppliers and customers are allocated and recorded.',
             'Third parties', 90, 'evidence')
        ) AS c(control_ref, title, requirement, section, ordinal, answer_mode)
        WHERE f.slug = 'iso-42001' AND f.org_id IS NULL;
    """)

    # NIST AI RMF 1.0 — subcategories across the four functions.
    op.execute("""
        INSERT INTO framework_controls
            (framework_id, org_id, control_ref, title, requirement, section, ordinal, answer_mode)
        SELECT f.id, NULL, c.control_ref, c.title, c.requirement, c.section, c.ordinal, c.answer_mode
        FROM frameworks f, (VALUES
            ('GOVERN 1.1', 'Legal and regulatory requirements understood',
             'Legal and regulatory requirements applying to the AI system are identified and managed.',
             'Govern', 10, 'hybrid'),
            ('GOVERN 2.1', 'Roles and responsibilities documented',
             'Roles, responsibilities and lines of authority for AI risk are documented and communicated.',
             'Govern', 20, 'evidence'),
            ('GOVERN 4.1', 'Risk culture and escalation',
             'Practices enable escalation of AI risks, and staff are empowered to raise them.',
             'Govern', 30, 'narrative'),
            ('GOVERN 6.1', 'Third-party risk addressed',
             'Risks from third-party models, data and tools are inventoried and managed.',
             'Govern', 40, 'evidence'),
            ('MAP 1.1',    'Context established',
             'The intended purpose, setting and limits of the AI system are established and documented.',
             'Map', 50, 'evidence'),
            ('MAP 2.3',    'Capabilities and limitations documented',
             'Scientific and technical capabilities, and known limitations, are documented.',
             'Map', 60, 'evidence'),
            ('MAP 4.1',    'Risks mapped to components',
             'Risks are mapped to the specific components and dependencies that create them.',
             'Map', 70, 'evidence'),
            ('MEASURE 2.1','System performance monitored',
             'AI system performance is measured against stated objectives in deployment.',
             'Measure', 80, 'evidence'),
            ('MEASURE 2.7','Security and resilience evaluated',
             'Security and resilience of the AI system are evaluated, including adversarial testing.',
             'Measure', 90, 'evidence'),
            ('MEASURE 3.1','Risk tracking mechanisms in place',
             'Mechanisms exist to track identified AI risks over time.',
             'Measure', 100, 'evidence'),
            ('MANAGE 1.1', 'Risk treatment decisions recorded',
             'Decisions to accept, mitigate or avoid identified AI risks are recorded with rationale.',
             'Manage', 110, 'evidence'),
            ('MANAGE 2.2', 'Mechanisms to sustain value',
             'Mechanisms are in place to sustain the AI system and respond to degradation.',
             'Manage', 120, 'evidence'),
            ('MANAGE 4.1', 'Post-deployment monitoring planned',
             'Post-deployment monitoring, including change detection, is planned and executed.',
             'Manage', 130, 'evidence')
        ) AS c(control_ref, title, requirement, section, ordinal, answer_mode)
        WHERE f.slug = 'nist-ai-rmf' AND f.org_id IS NULL;
    """)

    # EU AI Act — the high-risk obligations a client's counsel will ask about.
    op.execute("""
        INSERT INTO framework_controls
            (framework_id, org_id, control_ref, title, requirement, section, ordinal, answer_mode)
        SELECT f.id, NULL, c.control_ref, c.title, c.requirement, c.section, c.ordinal, c.answer_mode
        FROM frameworks f, (VALUES
            ('Article 9',  'Risk management system',
             'A risk management system runs across the lifecycle of the high-risk AI system.',
             'High-risk obligations', 10, 'hybrid'),
            ('Article 10', 'Data and data governance',
             'Training, validation and testing data meet quality criteria and are governed.',
             'High-risk obligations', 20, 'evidence'),
            ('Article 11', 'Technical documentation',
             'Technical documentation is drawn up before deployment and kept up to date.',
             'High-risk obligations', 30, 'evidence'),
            ('Article 12', 'Record-keeping',
             'The system logs events over its lifetime to a degree enabling traceability.',
             'High-risk obligations', 40, 'evidence'),
            ('Article 13', 'Transparency to deployers',
             'Operation is sufficiently transparent for deployers to interpret and use output.',
             'High-risk obligations', 50, 'hybrid'),
            ('Article 14', 'Human oversight',
             'The system can be effectively overseen by a natural person during use.',
             'High-risk obligations', 60, 'evidence'),
            ('Article 15', 'Accuracy, robustness and cybersecurity',
             'Appropriate levels of accuracy, robustness and cybersecurity are achieved and maintained.',
             'High-risk obligations', 70, 'evidence')
        ) AS c(control_ref, title, requirement, section, ordinal, answer_mode)
        WHERE f.slug = 'eu-ai-act' AND f.org_id IS NULL;
    """)

    # ------------------------------------------------------------------
    # Mappings. Evidence is produced once; these rows decide which control in
    # which framework it answers. This is what makes the second client's
    # questionnaire cost mapping rows instead of a new pipeline.
    # ------------------------------------------------------------------
    op.execute("""
        INSERT INTO control_mappings
            (control_id, org_id, evidence_kind, strength, producer, narrative_template)
        SELECT fc.id, NULL, m.evidence_kind, m.strength::mapping_strength,
               m.producer, m.narrative_template
        FROM framework_controls fc
        JOIN frameworks f ON f.id = fc.framework_id AND f.org_id IS NULL
        JOIN (VALUES
            -- ISO 42001
            ('iso-42001','A.3.2',  'ownership_record',        'satisfies',
             'ownership.current_holders',
             'Accountable owner and approver of record for {agent_name}, with validity dates.'),
            ('iso-42001','A.6.2.2','bom_completeness',        'satisfies',
             'bom.full_inventory',
             'Complete bill of materials for {agent_name} version {semver}.'),
            ('iso-42001','A.6.2.4','adversarial_probe',       'partially_satisfies',
             'probe.latest_results',
             'Adversarial probe results for {agent_name} version {semver}.'),
            ('iso-42001','A.6.2.6','service_level_attainment','satisfies',
             'sla.attainment_window',
             'Measured service-level attainment for {engagement_name} over {window}.'),
            ('iso-42001','A.7.2',  'data_class_inventory',    'satisfies',
             'bom.data_sources',
             'Data sources and classifications reached by {agent_name}.'),
            ('iso-42001','A.10.2', 'model_inventory',         'supports',
             'bom.models',
             'Third-party models and providers used by {agent_name}.'),

            -- NIST AI RMF
            ('nist-ai-rmf','GOVERN 2.1', 'ownership_record',   'satisfies',
             'ownership.current_holders',
             'Documented roles and responsibilities for {agent_name}.'),
            ('nist-ai-rmf','GOVERN 6.1', 'model_inventory',    'satisfies',
             'bom.third_party',
             'Inventory of third-party models, tools and MCP servers for {agent_name}.'),
            ('nist-ai-rmf','MAP 2.3',    'bom_completeness',   'partially_satisfies',
             'bom.full_inventory',
             'Declared capabilities and components of {agent_name} version {semver}.'),
            ('nist-ai-rmf','MAP 4.1',    'tool_permission_inventory','satisfies',
             'bom.tools_with_effects',
             'Tools reachable by {agent_name}, with declared effect and reversibility.'),
            ('nist-ai-rmf','MEASURE 2.1','service_level_attainment','satisfies',
             'sla.attainment_window',
             'Performance of {agent_name} against stated objectives over {window}.'),
            ('nist-ai-rmf','MEASURE 2.7','adversarial_probe',  'satisfies',
             'probe.latest_results',
             'Security and resilience evaluation for {agent_name} version {semver}.'),
            ('nist-ai-rmf','MEASURE 3.1','vulnerability_scan', 'satisfies',
             'cve.current_state',
             'Known vulnerabilities in components of {agent_name} version {semver}.'),
            ('nist-ai-rmf','MANAGE 1.1', 'materiality_verdict','satisfies',
             'materiality.decisions',
             'Recorded materiality decisions and rationale for {agent_name}.'),
            ('nist-ai-rmf','MANAGE 4.1', 'change_history',     'satisfies',
             'releases.since_accreditation',
             'Semantic changes to {agent_name} since accreditation {accreditation_ref}.'),

            -- EU AI Act
            ('eu-ai-act','Article 10','data_class_inventory',  'partially_satisfies',
             'bom.data_sources',
             'Data sources and classifications for {agent_name}.'),
            ('eu-ai-act','Article 11','bom_completeness',      'satisfies',
             'bom.full_inventory',
             'Technical composition of {agent_name} version {semver}.'),
            ('eu-ai-act','Article 12','chain_integrity',       'satisfies',
             'evidence.chain_verification',
             'Verified append-only event record for {agent_name} over {window}.'),
            ('eu-ai-act','Article 14','oversight_record',      'satisfies',
             'evidence.human_approvals',
             'Human approval and intervention events for {agent_name} over {window}.'),
            ('eu-ai-act','Article 15','vulnerability_scan',    'partially_satisfies',
             'cve.current_state',
             'Vulnerability state of {agent_name} version {semver}.')
        ) AS m(framework_slug, control_ref, evidence_kind, strength, producer, narrative_template)
          ON m.framework_slug = f.slug AND m.control_ref = fc.control_ref;
    """)

    # Residency evidence answers a control in every framework, so it is mapped
    # separately against whichever controls exist rather than enumerated per row.
    op.execute("""
        INSERT INTO control_mappings
            (control_id, org_id, evidence_kind, strength, producer, narrative_template)
        SELECT fc.id, NULL, 'residency_proof', 'satisfies',
               'residency.observed_vs_permitted',
               'Observed processing regions for {agent_name} against the permitted set for {customer_name}.'
        FROM framework_controls fc
        JOIN frameworks f ON f.id = fc.framework_id AND f.org_id IS NULL
        WHERE (f.slug, fc.control_ref) IN (
            ('iso-42001','A.7.2'),
            ('nist-ai-rmf','GOVERN 1.1'),
            ('eu-ai-act','Article 10')
        )
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS engagement_agents CASCADE;
        DROP TABLE IF EXISTS engagement_service_levels CASCADE;
        DROP TABLE IF EXISTS engagements CASCADE;
        DROP TABLE IF EXISTS customer_frameworks CASCADE;
        DROP TABLE IF EXISTS control_mappings CASCADE;
        DROP TABLE IF EXISTS framework_controls CASCADE;
        DROP TABLE IF EXISTS frameworks CASCADE;
        DROP TABLE IF EXISTS customer_contacts CASCADE;
        DROP TABLE IF EXISTS customers CASCADE;

        DROP TRIGGER IF EXISTS agents_touch_updated_at ON agents;
        DROP FUNCTION IF EXISTS touch_updated_at() CASCADE;

        DROP TYPE IF EXISTS version_uptake;
        DROP TYPE IF EXISTS mapping_strength;
        DROP TYPE IF EXISTS requirement_level;
        DROP TYPE IF EXISTS framework_kind;
        DROP TYPE IF EXISTS contact_role;
        DROP TYPE IF EXISTS engagement_state;
        DROP TYPE IF EXISTS criticality_tier;
        DROP TYPE IF EXISTS customer_status;
    """)

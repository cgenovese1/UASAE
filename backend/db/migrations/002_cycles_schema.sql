-- UASAE Assurance Cycles Schema — Migration 002
-- Run after 001_evidence_schema.sql.

-- ---------------------------------------------------------------------------
-- assurance_cycles
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS assurance_cycles (
    id                   UUID        PRIMARY KEY,
    started_at           TIMESTAMPTZ NOT NULL,
    completed_at         TIMESTAMPTZ,
    status               TEXT        NOT NULL
                             CHECK (status IN ('pending','running','completed','aborted')),
    cases_evaluated      INTEGER     NOT NULL DEFAULT 0,
    scenarios_compiled   INTEGER     NOT NULL DEFAULT 0,
    scenarios_executed   INTEGER     NOT NULL DEFAULT 0,
    verdicts             JSONB       NOT NULL DEFAULT '{}',
    regressions_detected INTEGER     NOT NULL DEFAULT 0,
    security_findings    INTEGER     NOT NULL DEFAULT 0,
    duration_seconds     FLOAT       NOT NULL DEFAULT 0.0,
    budget_seconds       INTEGER     NOT NULL DEFAULT 3600,
    errors               TEXT[]      NOT NULL DEFAULT '{}',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cycles_started  ON assurance_cycles (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_cycles_status   ON assurance_cycles (status);

-- ---------------------------------------------------------------------------
-- verification_cases (persisted from in-memory store)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS verification_cases (
    id                  UUID        PRIMARY KEY,
    version             TEXT        NOT NULL,
    intent              TEXT        NOT NULL,
    business_objective  TEXT        NOT NULL DEFAULT '',
    priority            TEXT        NOT NULL
                            CHECK (priority IN ('p0','p1','p2','p3','p4')),
    status              TEXT        NOT NULL
                            CHECK (status IN ('draft','active','superseded','retired')),
    uncertainty         FLOAT       NOT NULL DEFAULT 0.5,
    permanent_regression BOOLEAN    NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cases_priority ON verification_cases (priority);
CREATE INDEX IF NOT EXISTS idx_cases_status   ON verification_cases (status);

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
ALTER TABLE assurance_cycles   ENABLE ROW LEVEL SECURITY;
ALTER TABLE verification_cases ENABLE ROW LEVEL SECURITY;

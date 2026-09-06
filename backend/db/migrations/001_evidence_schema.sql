-- UASAE Evidence & Verdict Schema — Migration 001
-- Run against Supabase PostgreSQL on T340.
-- All tables use UUID primary keys and row-level security.

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- execution_runs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS execution_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id     UUID        NOT NULL,
    case_id         UUID        NOT NULL,
    adapter         TEXT        NOT NULL,
    environment     TEXT        NOT NULL DEFAULT 'test',
    status          TEXT        NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running','completed','failed','timeout','blocked')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    duration_ms     FLOAT,
    error           TEXT,
    evidence_bundle_id UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_runs_scenario ON execution_runs (scenario_id);
CREATE INDEX IF NOT EXISTS idx_runs_case     ON execution_runs (case_id);
CREATE INDEX IF NOT EXISTS idx_runs_status   ON execution_runs (status);

-- ---------------------------------------------------------------------------
-- evidence_bundles
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence_bundles (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id         UUID        NOT NULL REFERENCES execution_runs(id) ON DELETE CASCADE,
    scenario_id          UUID        NOT NULL,
    captured_at          TIMESTAMPTZ NOT NULL,
    request              JSONB,
    response             JSONB,
    ui_state             JSONB,
    database_state       JSONB,
    logs                 TEXT[]      NOT NULL DEFAULT '{}',
    metrics              JSONB       NOT NULL DEFAULT '{}',
    screenshot_ref       TEXT,
    dom_snapshot_ref     TEXT,
    trace_ref            TEXT,
    network_ref          TEXT,
    environment_snapshot JSONB       NOT NULL DEFAULT '{}',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bundles_scenario ON evidence_bundles (scenario_id);
CREATE INDEX IF NOT EXISTS idx_bundles_exec     ON evidence_bundles (execution_id);

-- ---------------------------------------------------------------------------
-- verdicts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS verdicts (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id   UUID        NOT NULL REFERENCES execution_runs(id) ON DELETE CASCADE,
    case_id        UUID        NOT NULL,
    scenario_id    UUID        NOT NULL,
    status         TEXT        NOT NULL
                       CHECK (status IN ('verified','failed','unknown','unobservable')),
    confidence     FLOAT       NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    risk_impact    FLOAT       NOT NULL DEFAULT 0.0,
    provenance     TEXT[]      NOT NULL DEFAULT '{}',
    evidence_ids   UUID[]      NOT NULL DEFAULT '{}',
    notes          TEXT        NOT NULL DEFAULT '',
    determined_at  TIMESTAMPTZ NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_verdicts_scenario ON verdicts (scenario_id);
CREATE INDEX IF NOT EXISTS idx_verdicts_case     ON verdicts (case_id);
CREATE INDEX IF NOT EXISTS idx_verdicts_status   ON verdicts (status);
CREATE INDEX IF NOT EXISTS idx_verdicts_exec     ON verdicts (execution_id);

-- ---------------------------------------------------------------------------
-- assurance_memory  (Phase 12 baseline — schema only)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS assurance_memory (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id        UUID        NOT NULL,
    scenario_id    UUID        NOT NULL,
    baseline_status TEXT       NOT NULL,
    baseline_confidence FLOAT  NOT NULL,
    established_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    superseded_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_memory_case ON assurance_memory (case_id);

-- ---------------------------------------------------------------------------
-- Row Level Security (all tables owner-only by default)
-- ---------------------------------------------------------------------------
ALTER TABLE execution_runs    ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_bundles  ENABLE ROW LEVEL SECURITY;
ALTER TABLE verdicts          ENABLE ROW LEVEL SECURITY;
ALTER TABLE assurance_memory  ENABLE ROW LEVEL SECURITY;

-- Service role bypasses RLS; anon/authenticated roles need explicit policies.
-- Add policies per-deployment based on multi-tenancy requirements.

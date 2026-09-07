/**
 * UASAE API client — typed fetch wrappers for all backend endpoints.
 * All requests go through the Next.js rewrite proxy to the FastAPI backend.
 */

const BASE = "/api";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`);
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Types (mirror backend ontology)
// ---------------------------------------------------------------------------

export type VerdictStatus = "verified" | "failed" | "unknown" | "unobservable";
export type Priority = "p0" | "p1" | "p2" | "p3";
export type CaseStatus = "draft" | "active" | "superseded" | "retired";

export interface VerificationCase {
  id: string;
  intent: string;
  version: string;
  priority: Priority;
  status: CaseStatus;
  business_objective: string;
  uncertainty: number;
}

export interface VerdictSummary {
  id: string;
  scenario_id: string;
  case_id: string;
  status: VerdictStatus;
  confidence: number;
  determined_at: string;
  provenance: string[];
}

export interface RiskEntry {
  case_id: string;
  score: number;
  priority: Priority;
  coverage_gap: number;
  rationale: string[];
}

export interface HealthStatus {
  status: string;
  service: string;
  env: string;
}

export interface CycleReport {
  cycle_id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  cases_evaluated: number;
  scenarios_compiled: number;
  scenarios_executed: number;
  verdicts: Record<string, number>;
  regressions_detected: number;
  security_findings: number;
  duration_seconds: number;
  budget_seconds: number;
  errors: string[];
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`);
  return res.json() as Promise<T>;
}

export const api = {
  health: () => get<HealthStatus>("/health"),

  cases: {
    list: (limit = 50) =>
      get<{ total: number; cases: VerificationCase[] }>(`/verification/cases?limit=${limit}`),
    get: (caseId: string) =>
      get<VerificationCase>(`/verification/cases/${caseId}`),
    generateFromInvariants: () =>
      post<{ generated: number; cases: VerificationCase[] }>(
        "/verification/cases/from-invariants",
        {}
      ),
  },

  verdicts: {
    listForCase: (caseId: string, limit = 20) =>
      get<{ total: number; verdicts: VerdictSummary[] }>(
        `/evidence/verdicts?case_id=${caseId}&limit=${limit}`
      ),
    latest: (scenarioId: string) =>
      get<VerdictSummary>(`/evidence/verdicts/latest/${scenarioId}`),
  },

  cycles: {
    list: (limit = 50) =>
      get<{ total: number; cycles: CycleReport[] }>(`/execution/cycles?limit=${limit}`),
    get: (cycleId: string) =>
      get<CycleReport>(`/execution/cycles/${cycleId}`),
    trigger: (opts?: { environment?: string; budget_seconds?: number; changed_files?: string[] }) =>
      post<{ message: string; environment: string; budget_seconds: number; poll: string }>(
        "/execution/cycles",
        opts ?? {}
      ),
    triggerSync: (opts?: { environment?: string; budget_seconds?: number }) =>
      post<CycleReport & { summary: string }>(
        "/execution/cycles/sync",
        opts ?? {}
      ),
  },

  mcp: {
    riskSummary: (topN = 10) =>
      fetch(`${BASE}/mcp/risk-summary?top_n=${topN}`, { cache: "no-store" }).then(
        (r) => r.json() as Promise<{ top_risks: RiskEntry[] }>
      ),
  },
};

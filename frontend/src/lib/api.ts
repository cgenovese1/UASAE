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

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

export const api = {
  health: () => get<HealthStatus>("/health"),

  cases: {
    list: (limit = 50) =>
      get<{ total: number; cases: VerificationCase[] }>(`/verification/cases?limit=${limit}`),
  },

  verdicts: {
    listForCase: (caseId: string, limit = 20) =>
      get<{ total: number; verdicts: VerdictSummary[] }>(
        `/evidence/verdicts?case_id=${caseId}&limit=${limit}`
      ),
    latest: (scenarioId: string) =>
      get<VerdictSummary>(`/evidence/verdicts/latest/${scenarioId}`),
  },

  mcp: {
    riskSummary: (topN = 10) =>
      fetch(`${BASE}/mcp/risk-summary?top_n=${topN}`, { cache: "no-store" }).then(
        (r) => r.json() as Promise<{ top_risks: RiskEntry[] }>
      ),
  },
};

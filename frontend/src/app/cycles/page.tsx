"use client";

import { useEffect, useState } from "react";
import type { CycleReport } from "@/lib/api";

async function fetchCycles(): Promise<{ total: number; cycles: CycleReport[] } | null> {
  try {
    const res = await fetch("/api/execution/cycles?limit=50", { cache: "no-store" });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

async function triggerCycle(environment: string, budget: number): Promise<CycleReport | null> {
  try {
    const res = await fetch("/api/execution/cycles/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ environment, budget_seconds: budget }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error((err as { detail?: string }).detail || res.statusText);
    }
    return res.json();
  } catch (e) {
    throw e;
  }
}

function StatusBadge({ status }: { status: string }) {
  const style =
    status === "completed"
      ? "bg-green-900 text-green-300 border border-green-800"
      : status === "aborted"
      ? "bg-red-900 text-red-300 border border-red-800"
      : status === "running"
      ? "bg-blue-900 text-blue-300 border border-blue-800"
      : "bg-gray-800 text-gray-400 border border-gray-700";
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${style}`}>
      {status}
    </span>
  );
}

function VerdictSpark({ verdicts }: { verdicts: Record<string, number> }) {
  const total = Object.values(verdicts).reduce((a, b) => a + b, 0);
  if (total === 0) return <span className="text-xs text-gray-600">—</span>;
  const verified = verdicts.verified ?? 0;
  const failed = verdicts.failed ?? 0;
  return (
    <span className="text-xs tabular-nums">
      <span className="text-green-400">{verified}✓</span>
      {failed > 0 && <span className="ml-1 text-red-400">{failed}✗</span>}
      <span className="ml-1 text-gray-500">/{total}</span>
    </span>
  );
}

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function CyclesPage() {
  const [data, setData] = useState<{ total: number; cycles: CycleReport[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [env, setEnv] = useState("test");
  const [budget, setBudget] = useState(300);

  async function load() {
    setLoading(true);
    const result = await fetchCycles();
    setData(result);
    setLoading(false);
  }

  useEffect(() => {
    load();
  }, []);

  async function handleTrigger() {
    setRunning(true);
    setError(null);
    try {
      await triggerCycle(env, budget);
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  const cycles = data?.cycles ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Assurance Cycles</h1>
          <p className="mt-1 text-sm text-gray-400">
            Each cycle runs DISCOVER → COMPILE → PLAN → EXECUTE → INVESTIGATE.
            {data ? ` ${data.total} cycles on record.` : ""}
          </p>
        </div>

        {/* Trigger panel */}
        <div className="flex items-end gap-2">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">Environment</label>
            <select
              value={env}
              onChange={(e) => setEnv(e.target.value)}
              className="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-200"
              disabled={running}
            >
              <option value="test">test</option>
              <option value="staging">staging</option>
              <option value="production">production</option>
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">Budget (s)</label>
            <input
              type="number"
              value={budget}
              onChange={(e) => setBudget(Number(e.target.value))}
              className="w-20 rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-200"
              min={30}
              max={3600}
              disabled={running}
            />
          </div>
          <button
            onClick={handleTrigger}
            disabled={running}
            className="rounded bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
          >
            {running ? "Running…" : "Run Cycle"}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded border border-red-800 bg-red-950 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {running && (
        <div className="rounded border border-blue-800 bg-blue-950 px-4 py-3 text-sm text-blue-300">
          Assurance cycle running — compiling scenarios and executing adapters…
        </div>
      )}

      {loading && !running ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : cycles.length === 0 ? (
        <div className="rounded-lg border border-gray-800 bg-gray-900 p-8 text-center">
          <p className="text-sm text-gray-400">No assurance cycles recorded yet.</p>
          <p className="mt-2 text-xs text-gray-600">
            Use the <strong className="text-gray-400">Run Cycle</strong> button above to trigger the first cycle.
            Make sure verification cases exist first (generate them via the Verification Cases page).
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 bg-gray-900">
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Started</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Cases</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Scenarios</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Verdicts</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Regressions</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Duration</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {cycles.map((c) => (
                <tr key={c.cycle_id} className="hover:bg-gray-900 transition-colors">
                  <td className="px-4 py-3">
                    <StatusBadge status={c.status} />
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400 tabular-nums">
                    {formatDate(c.started_at)}
                  </td>
                  <td className="px-4 py-3 text-gray-300 tabular-nums">{c.cases_evaluated}</td>
                  <td className="px-4 py-3 text-gray-300 tabular-nums">{c.scenarios_executed}</td>
                  <td className="px-4 py-3">
                    <VerdictSpark verdicts={c.verdicts} />
                  </td>
                  <td className="px-4 py-3 tabular-nums">
                    {c.regressions_detected > 0 ? (
                      <span className="text-red-400">{c.regressions_detected}</span>
                    ) : (
                      <span className="text-gray-600">0</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400 tabular-nums">
                    {c.duration_seconds.toFixed(1)}s
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

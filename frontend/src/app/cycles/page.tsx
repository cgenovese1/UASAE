/**
 * Assurance Cycles page — shows historical cycle reports fetched from the backend.
 * Until cycles are stored persistently, the page shows a useful empty state.
 */

export const dynamic = "force-dynamic";

async function getCycles() {
  try {
    const res = await fetch(
      `${process.env.BACKEND_URL || "http://localhost:8000"}/api/execution/cycles?limit=50`,
      { cache: "no-store" }
    );
    if (!res.ok) return null;
    return res.json() as Promise<{
      total: number;
      cycles: Array<{
        cycle_id: string;
        status: string;
        started_at: string;
        completed_at: string | null;
        cases_evaluated: number;
        scenarios_executed: number;
        verdicts: Record<string, number>;
        regressions_detected: number;
        duration_seconds: number;
      }>;
    }>;
  } catch {
    return null;
  }
}

function StatusBadge({ status }: { status: string }) {
  const style =
    status === "completed"
      ? "bg-green-900 text-green-300"
      : status === "aborted"
      ? "bg-red-900 text-red-300"
      : "bg-blue-900 text-blue-300";
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

export default async function CyclesPage() {
  const data = await getCycles();
  const cycles = data?.cycles ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Assurance Cycles</h1>
        <p className="mt-1 text-sm text-gray-400">
          Each cycle runs DISCOVER → COMPILE → PLAN → EXECUTE → INVESTIGATE.
          {data ? ` ${data.total} cycles on record.` : ""}
        </p>
      </div>

      {cycles.length === 0 ? (
        <div className="rounded-lg border border-gray-800 bg-gray-900 p-8 text-center">
          <p className="text-sm text-gray-400">No assurance cycles recorded yet.</p>
          <p className="mt-2 text-xs text-gray-600">
            Trigger a cycle via the CLI or API to see results here.
          </p>
          <pre className="mt-4 inline-block rounded bg-gray-950 px-4 py-2 text-left text-xs text-gray-400">
            POST /api/execution/cycles
          </pre>
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

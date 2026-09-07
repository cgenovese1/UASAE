import { api } from "@/lib/api";
import type { VerificationCase } from "@/lib/api";

export const dynamic = "force-dynamic";

async function getCases() {
  try {
    return await api.cases.list(200);
  } catch {
    return null;
  }
}

function PriorityBadge({ priority }: { priority: string }) {
  const color: Record<string, string> = {
    p0: "bg-red-900 text-red-300 border border-red-700",
    p1: "bg-orange-900 text-orange-300 border border-orange-700",
    p2: "bg-yellow-900 text-yellow-300 border border-yellow-700",
    p3: "bg-gray-800 text-gray-400 border border-gray-700",
  };
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-mono font-medium ${color[priority] ?? color.p3}`}>
      {priority.toUpperCase()}
    </span>
  );
}

function UncertaintyBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.7 ? "bg-red-500" : value >= 0.4 ? "bg-yellow-500" : "bg-green-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 rounded-full bg-gray-800">
        <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-gray-500">{pct}%</span>
    </div>
  );
}

export default async function CasesPage() {
  const data = await getCases();
  const cases: VerificationCase[] = data?.cases ?? [];

  const byPriority: Record<string, VerificationCase[]> = {};
  for (const c of cases) {
    (byPriority[c.priority] ??= []).push(c);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Verification Cases</h1>
        <p className="mt-1 text-sm text-gray-400">
          {data ? `${data.total} cases across all priorities` : "Backend unreachable"}
        </p>
      </div>

      {cases.length === 0 ? (
        <p className="text-sm text-gray-500">No cases found. Run a repository analysis to generate them.</p>
      ) : (
        <>
          <div className="grid grid-cols-4 gap-3">
            {["p0", "p1", "p2", "p3"].map((p) => (
              <div key={p} className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                <PriorityBadge priority={p} />
                <p className="mt-2 text-2xl font-semibold tabular-nums">{byPriority[p]?.length ?? 0}</p>
              </div>
            ))}
          </div>

          <div className="overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 bg-gray-900">
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Priority</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Intent</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Status</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Uncertainty</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Version</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {cases.map((c) => (
                  <tr key={c.id} className="hover:bg-gray-900 transition-colors">
                    <td className="px-4 py-3">
                      <PriorityBadge priority={c.priority} />
                    </td>
                    <td className="px-4 py-3 text-gray-200 max-w-md">
                      <p className="truncate">{c.intent}</p>
                      {c.business_objective && (
                        <p className="mt-0.5 truncate text-xs text-gray-500">{c.business_objective}</p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-400 text-xs">{c.status}</td>
                    <td className="px-4 py-3">
                      <UncertaintyBar value={c.uncertainty} />
                    </td>
                    <td className="px-4 py-3 text-gray-500 font-mono text-xs">{c.version}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

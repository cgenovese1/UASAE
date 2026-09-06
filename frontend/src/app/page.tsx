import { api } from "@/lib/api";

async function getStats() {
  try {
    const [health, cases] = await Promise.allSettled([
      api.health(),
      api.cases.list(200),
    ]);
    return {
      health: health.status === "fulfilled" ? health.value : null,
      cases: cases.status === "fulfilled" ? cases.value : null,
    };
  } catch {
    return { health: null, cases: null };
  }
}

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 p-5">
      <p className="text-sm text-gray-400">{label}</p>
      <p className="mt-1 text-3xl font-semibold tabular-nums">{value}</p>
      {sub && <p className="mt-1 text-xs text-gray-500">{sub}</p>}
    </div>
  );
}

function PriorityBadge({ priority }: { priority: string }) {
  const color: Record<string, string> = {
    p0: "bg-red-900 text-red-300",
    p1: "bg-orange-900 text-orange-300",
    p2: "bg-yellow-900 text-yellow-300",
    p3: "bg-gray-800 text-gray-400",
  };
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${color[priority] ?? color.p3}`}>
      {priority.toUpperCase()}
    </span>
  );
}

export default async function DashboardPage() {
  const { health, cases } = await getStats();

  const caseList = cases?.cases ?? [];
  const byPriority = caseList.reduce<Record<string, number>>((acc, c) => {
    acc[c.priority] = (acc[c.priority] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <p className="mt-1 text-sm text-gray-400">
          {health
            ? `Backend ${health.env} — ${health.status}`
            : "Backend unreachable"}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Total Cases" value={cases?.total ?? "—"} />
        <StatCard label="P0 Invariants" value={byPriority.p0 ?? 0} sub="always verified" />
        <StatCard label="P1 Cases" value={byPriority.p1 ?? 0} />
        <StatCard label="P2+ Cases" value={(byPriority.p2 ?? 0) + (byPriority.p3 ?? 0)} />
      </div>

      <div>
        <h2 className="mb-3 text-base font-medium">Verification Cases</h2>
        {caseList.length === 0 ? (
          <p className="text-sm text-gray-500">No cases found. Run a repository analysis to generate them.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-gray-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 bg-gray-900">
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Priority</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Intent</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Status</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Version</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {caseList.slice(0, 20).map((c) => (
                  <tr key={c.id} className="hover:bg-gray-900 transition-colors">
                    <td className="px-4 py-3">
                      <PriorityBadge priority={c.priority} />
                    </td>
                    <td className="px-4 py-3 text-gray-200 max-w-md truncate">{c.intent}</td>
                    <td className="px-4 py-3 text-gray-400">{c.status}</td>
                    <td className="px-4 py-3 text-gray-500 font-mono text-xs">{c.version}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

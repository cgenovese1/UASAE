export const dynamic = "force-dynamic";

async function getRiskData() {
  try {
    const res = await fetch(
      `${process.env.BACKEND_URL || "http://localhost:8000"}/api/verification/cases?limit=200`,
      { cache: "no-store" }
    );
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

function RiskBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = score >= 0.8 ? "bg-red-500" : score >= 0.6 ? "bg-orange-500" : score >= 0.4 ? "bg-yellow-500" : "bg-green-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-32 rounded-full bg-gray-800">
        <div className={`h-2 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-gray-400">{pct}%</span>
    </div>
  );
}

export default async function RiskPage() {
  const data = await getRiskData();
  const cases = data?.cases ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Risk Summary</h1>
        <p className="mt-1 text-sm text-gray-400">
          Verification cases ranked by urgency. P0 invariants always appear first.
        </p>
      </div>

      {cases.length === 0 ? (
        <p className="text-sm text-gray-500">No cases available. Connect a repository to generate cases.</p>
      ) : (
        <div className="rounded-lg border border-gray-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 bg-gray-900">
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">#</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Priority</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Intent</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Risk Score</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {cases.map((c: { id: string; intent: string; priority: string }, i: number) => (
                <tr key={c.id} className="hover:bg-gray-900 transition-colors">
                  <td className="px-4 py-3 text-gray-500 tabular-nums">{i + 1}</td>
                  <td className="px-4 py-3">
                    <span className="font-mono text-xs uppercase text-gray-300">{c.priority}</span>
                  </td>
                  <td className="px-4 py-3 text-gray-200 max-w-sm truncate">{c.intent}</td>
                  <td className="px-4 py-3">
                    <RiskBar score={c.priority === "p0" ? 1.0 : c.priority === "p1" ? 0.65 : 0.40} />
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

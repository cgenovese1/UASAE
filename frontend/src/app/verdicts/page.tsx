import { api } from "@/lib/api";
import type { VerificationCase, VerdictSummary } from "@/lib/api";

export const dynamic = "force-dynamic";

async function getData() {
  try {
    const casesData = await api.cases.list(50);
    const cases = casesData.cases;

    const verdictsPerCase = await Promise.allSettled(
      cases.map((c) => api.verdicts.listForCase(c.id, 5))
    );

    const verdicts: Array<VerdictSummary & { case_intent: string }> = [];
    for (let i = 0; i < cases.length; i++) {
      const result = verdictsPerCase[i];
      if (result.status === "fulfilled") {
        for (const v of result.value.verdicts) {
          verdicts.push({ ...v, case_intent: cases[i].intent });
        }
      }
    }

    verdicts.sort(
      (a, b) => new Date(b.determined_at).getTime() - new Date(a.determined_at).getTime()
    );

    return { cases, verdicts: verdicts.slice(0, 100) };
  } catch {
    return null;
  }
}

const STATUS_STYLE: Record<string, string> = {
  verified: "bg-green-900 text-green-300",
  failed: "bg-red-900 text-red-300",
  unknown: "bg-gray-800 text-gray-400",
  unobservable: "bg-purple-900 text-purple-300",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[status] ?? STATUS_STYLE.unknown}`}>
      {status}
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.8 ? "bg-green-500" : value >= 0.5 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 rounded-full bg-gray-800">
        <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-gray-500">{pct}%</span>
    </div>
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

export default async function VerdictsPage() {
  const data = await getData();

  if (!data) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold">Verdicts</h1>
        <p className="text-sm text-gray-500">Backend unreachable.</p>
      </div>
    );
  }

  const { verdicts } = data;
  const counts = verdicts.reduce<Record<string, number>>((acc, v) => {
    acc[v.status] = (acc[v.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Verdicts</h1>
        <p className="mt-1 text-sm text-gray-400">
          Most recent verification outcomes across all cases.
        </p>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Verified", key: "verified", cls: "text-green-400" },
          { label: "Failed", key: "failed", cls: "text-red-400" },
          { label: "Unknown", key: "unknown", cls: "text-gray-400" },
          { label: "Unobservable", key: "unobservable", cls: "text-purple-400" },
        ].map(({ label, key, cls }) => (
          <div key={key} className="rounded-lg border border-gray-800 bg-gray-900 p-4">
            <p className="text-xs text-gray-500">{label}</p>
            <p className={`mt-1 text-2xl font-semibold tabular-nums ${cls}`}>
              {counts[key] ?? 0}
            </p>
          </div>
        ))}
      </div>

      {verdicts.length === 0 ? (
        <p className="text-sm text-gray-500">No verdicts recorded yet. Execute verification scenarios to see results here.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 bg-gray-900">
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Case Intent</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Confidence</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Determined</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {verdicts.map((v) => (
                <tr key={v.id} className="hover:bg-gray-900 transition-colors">
                  <td className="px-4 py-3">
                    <StatusBadge status={v.status} />
                  </td>
                  <td className="px-4 py-3 text-gray-200 max-w-sm">
                    <p className="truncate">{v.case_intent}</p>
                    <p className="mt-0.5 font-mono text-xs text-gray-600 truncate">{v.scenario_id}</p>
                  </td>
                  <td className="px-4 py-3">
                    <ConfidenceBar value={v.confidence} />
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400 tabular-nums">
                    {formatDate(v.determined_at)}
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

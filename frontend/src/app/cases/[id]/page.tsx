import { api } from "@/lib/api";
import type { VerdictSummary } from "@/lib/api";

export const dynamic = "force-dynamic";

async function getData(id: string) {
  try {
    const [caseData, verdictsData] = await Promise.allSettled([
      api.cases.get(id),
      api.verdicts.listForCase(id, 50),
    ]);
    return {
      case: caseData.status === "fulfilled" ? caseData.value : null,
      verdicts: verdictsData.status === "fulfilled" ? verdictsData.value : null,
    };
  } catch {
    return { case: null, verdicts: null };
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

function PriorityBadge({ priority }: { priority: string }) {
  const color: Record<string, string> = {
    p0: "bg-red-900 text-red-300",
    p1: "bg-orange-900 text-orange-300",
    p2: "bg-yellow-900 text-yellow-300",
    p3: "bg-gray-800 text-gray-400",
  };
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-mono font-medium ${color[priority] ?? color.p3}`}>
      {priority.toUpperCase()}
    </span>
  );
}

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

export default async function CaseDetailPage({ params }: { params: { id: string } }) {
  const { case: c, verdicts: vData } = await getData(params.id);
  const verdicts: VerdictSummary[] = vData?.verdicts ?? [];

  if (!c) {
    return (
      <div className="space-y-4">
        <a href="/cases" className="text-sm text-indigo-400 hover:text-indigo-300">← Cases</a>
        <p className="text-sm text-gray-500">Case not found or backend unreachable.</p>
      </div>
    );
  }

  const verdictCounts = verdicts.reduce<Record<string, number>>((acc, v) => {
    acc[v.status] = (acc[v.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <div>
        <a href="/cases" className="text-sm text-indigo-400 hover:text-indigo-300">← Cases</a>
        <div className="mt-3 flex items-start gap-3">
          <PriorityBadge priority={c.priority} />
          <div>
            <h1 className="text-xl font-semibold leading-tight">{c.intent}</h1>
            {c.business_objective && (
              <p className="mt-1 text-sm text-gray-400">{c.business_objective}</p>
            )}
          </div>
        </div>
        <div className="mt-3 flex gap-4 text-xs text-gray-500">
          <span>Status: <span className="text-gray-300">{c.status}</span></span>
          <span>Version: <span className="font-mono text-gray-300">{c.version}</span></span>
          <span>Uncertainty: <span className="text-gray-300">{Math.round(c.uncertainty * 100)}%</span></span>
        </div>
      </div>

      {/* Verdict summary */}
      <div>
        <h2 className="mb-3 text-base font-medium">Verification Verdicts</h2>
        {verdicts.length === 0 ? (
          <p className="text-sm text-gray-500">
            No verdicts yet. Compile scenarios and run an assurance cycle to see results.
          </p>
        ) : (
          <>
            <div className="mb-4 grid grid-cols-4 gap-3">
              {["verified", "failed", "unknown", "unobservable"].map((s) => (
                <div key={s} className="rounded-lg border border-gray-800 bg-gray-900 p-3">
                  <p className="text-xs text-gray-500 capitalize">{s}</p>
                  <p className="mt-1 text-2xl font-semibold tabular-nums">{verdictCounts[s] ?? 0}</p>
                </div>
              ))}
            </div>

            <div className="overflow-x-auto rounded-lg border border-gray-800">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-800 bg-gray-900">
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Status</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400">Scenario</th>
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
                      <td className="px-4 py-3 font-mono text-xs text-gray-500 max-w-xs truncate">
                        {v.scenario_id}
                      </td>
                      <td className="px-4 py-3 text-xs tabular-nums text-gray-300">
                        {Math.round(v.confidence * 100)}%
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-400 tabular-nums">
                        {formatDate(v.determined_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { verificationFlagsApi } from "../../api";
import { CheckCircle2, Circle } from "lucide-react";
import { fmt, parseServerDateTime } from "../../lib/utils";

const FEATURE_LABELS: Record<string, string> = {
  forecast: "Forecast",
  transactions: "Transactions",
  household_snapshot: "Household Snapshot",
};

export default function VerificationFeedbackTab() {
  const qc = useQueryClient();
  const [showResolved, setShowResolved] = useState(false);
  const { data: flags = [] } = useQuery({
    queryKey: ["verification-flags", showResolved],
    queryFn: () => verificationFlagsApi.list(showResolved ? {} : { status: "open" }),
  });
  const resolveMut = useMutation({
    mutationFn: ({ id, newStatus }: { id: number; newStatus: "open" | "resolved" }) =>
      verificationFlagsApi.resolve(id, newStatus),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["verification-flags"] }),
  });

  // Grouped by feature (Forecast / Transactions / Household Snapshot) rather
  // than one flat chronological list -- each feature is its own review
  // queue, and grouping keeps a burst of transaction flags from burying a
  // single forecast flag underneath them.
  const groups: Record<string, any[]> = { forecast: [], transactions: [], household_snapshot: [] };
  for (const flag of flags) {
    (groups[flag.feature] ??= []).push(flag);
  }

  function renderFlag(flag: any) {
    let observed: Record<string, unknown> = {};
    try {
      observed = JSON.parse(flag.observed_json);
    } catch {
      // malformed row -- fall through, the raw fields below still render
    }
    return (
      <div key={flag.id} className="p-3 rounded-lg border border-gray-100 dark:border-gray-700">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-xs text-gray-400">{parseServerDateTime(flag.created_at).toLocaleString()}</p>
            {flag.expected_value != null && (
              <p className="text-sm text-gray-700 dark:text-gray-300 mt-1">
                Expected: <strong>{fmt(flag.expected_value)}</strong>
              </p>
            )}
            {flag.note && <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">{flag.note}</p>}
            <pre className="text-[10px] text-gray-400 dark:text-gray-400 mt-1 whitespace-pre-wrap break-words">
              {JSON.stringify(observed)}
            </pre>
          </div>
          <button
            onClick={() => resolveMut.mutate({ id: flag.id, newStatus: flag.status === "open" ? "resolved" : "open" })}
            className="shrink-0 text-gray-300 hover:text-emerald-500"
            title={flag.status === "open" ? "Mark resolved" : "Reopen"}
          >
            {flag.status === "open" ? <Circle size={16} /> : <CheckCircle2 size={16} className="text-emerald-500" />}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">Verification Feedback</h3>
          <p className="text-xs text-gray-400">Numbers flagged as wrong while Parallel Ops was on</p>
        </div>
        <label className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
          <input
            type="checkbox"
            className="w-3.5 h-3.5 rounded accent-indigo-600"
            checked={showResolved}
            onChange={(e) => setShowResolved(e.target.checked)}
          />
          Show resolved
        </label>
      </div>
      {flags.length === 0 && <p className="text-sm text-gray-400 text-center py-8">No flags yet</p>}
      <div className="space-y-5">
        {Object.entries(groups).map(([feature, featureFlags]) =>
          featureFlags.length === 0 ? null : (
            <div key={feature}>
              <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase mb-2">
                {FEATURE_LABELS[feature] ?? feature}
              </p>
              <div className="space-y-2">{featureFlags.map(renderFlag)}</div>
            </div>
          )
        )}
      </div>
    </div>
  );
}

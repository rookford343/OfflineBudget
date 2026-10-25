import { fmt, fmtDate } from "../../lib/utils";
import { useBalancesHidden, maskIfHidden } from "../../store/balanceVisibility";
import { X } from "lucide-react";

interface PlaidFirstImportRow {
  date: string;
  amount: string;
  description: string;
  outcome: string;
  target: string;
}

interface PlaidFirstImportData {
  imported: number;
  matched: number;
  ignored: number;
  rows: PlaidFirstImportRow[];
}

function outcomeBadge(outcome: string): string {
  if (outcome === "imported") return "badge-blue";
  if (outcome === "matched") return "badge-green";
  return "badge-amber"; // ignored
}

/**
 * The dry-run preview for a Plaid connection's first import: counts plus a
 * scrollable row-by-row breakdown, with a Confirm button that re-calls the
 * same endpoint with confirm=true. Split out of AccountsTab.tsx purely for
 * size -- all the data/mutation state still lives there.
 */
export default function PlaidFirstImportPreview(
  { data, onClose, onConfirm, confirming }:
  { data: PlaidFirstImportData; onClose: () => void; onConfirm: () => void; confirming: boolean },
) {
  const hidden = useBalancesHidden();

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="card w-full max-w-lg max-h-[85vh] flex flex-col">
        <div className="flex justify-between items-center mb-3">
          <h3 className="font-bold text-gray-900 dark:text-gray-100">First import preview</h3>
          <button onClick={onClose} className="btn-ghost p-1"><X size={18} /></button>
        </div>
        <div className="flex items-center gap-4 mb-3 text-xs text-gray-600 dark:text-gray-300">
          <span><span className="font-semibold text-gray-900 dark:text-gray-100">{data.imported}</span> to import</span>
          <span><span className="font-semibold text-gray-900 dark:text-gray-100">{data.matched}</span> matched</span>
          <span><span className="font-semibold text-gray-900 dark:text-gray-100">{data.ignored}</span> ignored</span>
        </div>
        <div className="flex-1 overflow-y-auto divide-y divide-gray-100 dark:divide-gray-700 -mx-1 px-1">
          {data.rows.map((r, i) => (
            <div key={i} className="py-2 flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="text-xs text-gray-900 dark:text-gray-100 truncate">{fmtDate(r.date)} — {r.description}</p>
                <p className="text-xs text-gray-400">{r.target}</p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-xs tabular-nums text-gray-700 dark:text-gray-200">{maskIfHidden(hidden, fmt(r.amount))}</span>
                <span className={outcomeBadge(r.outcome)}>{r.outcome}</span>
              </div>
            </div>
          ))}
          {data.rows.length === 0 && <p className="text-sm text-gray-400 py-4 text-center">No transactions found</p>}
        </div>
        <div className="flex gap-3 pt-4">
          <button onClick={onConfirm} disabled={confirming} className="btn-primary flex-1">
            {confirming ? "Importing…" : "Confirm import"}
          </button>
          <button onClick={onClose} disabled={confirming} className="btn-secondary flex-1">Cancel</button>
        </div>
      </div>
    </div>
  );
}

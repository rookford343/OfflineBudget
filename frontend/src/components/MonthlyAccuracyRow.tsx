import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { forecastApi, dayCheckpointsApi, transactionsApi, recurringApi } from "../api";
import { fmt } from "../lib/utils";
import { ChevronDown, ChevronUp, CheckCircle, AlertTriangle, XCircle, Link2 } from "lucide-react";

interface Props {
  accountId: number;
  year: number;
  month: number;
}

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function lastDayOfMonth(year: number, month: number): string {
  const d = new Date(year, month, 0);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export default function MonthlyAccuracyRow({ accountId, year, month }: Props) {
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [anchorEditing, setAnchorEditing] = useState(false);
  const [anchorValue, setAnchorValue] = useState("");
  const [linkingTxnId, setLinkingTxnId] = useState<number | null>(null);
  const [linkRecurringId, setLinkRecurringId] = useState<string>("");

  const { data, isLoading } = useQuery({
    queryKey: ["monthly-summary", accountId, year, month],
    queryFn: () => forecastApi.monthlySummary(accountId, year, month),
    enabled: expanded,
    staleTime: 5 * 60 * 1000,
  });

  const { data: recurringItems = [] } = useQuery<any[]>({
    queryKey: ["recurring"],
    queryFn: () => recurringApi.list(),
    enabled: expanded,
    staleTime: 30 * 1000,
  });

  const monthEndDate = lastDayOfMonth(year, month);

  const saveAnchorMut = useMutation({
    mutationFn: (balance: number) =>
      dayCheckpointsApi.upsert(monthEndDate, accountId, balance, "Month-end balance"),
    onSuccess: () => {
      setAnchorEditing(false);
      setAnchorValue("");
      qc.invalidateQueries({ queryKey: ["monthly-summary", accountId, year, month] });
      qc.invalidateQueries({ queryKey: ["day-checkpoints"] });
      qc.invalidateQueries({ queryKey: ["forecast-quarters"] });
      qc.invalidateQueries({ queryKey: ["forecast-multi-year"] });
    },
  });

  const linkTxnMut = useMutation({
    mutationFn: ({ txnId, recurringItemId }: { txnId: number; recurringItemId: number }) =>
      transactionsApi.update(txnId, { recurring_item_id: recurringItemId }),
    onSuccess: () => {
      setLinkingTxnId(null);
      setLinkRecurringId("");
      qc.invalidateQueries({ queryKey: ["monthly-summary", accountId, year, month] });
    },
  });

  const delta = data?.delta != null ? parseFloat(data.delta) : null;
  const deltaAbs = delta != null ? Math.abs(delta) : null;
  const deltaColor =
    deltaAbs == null ? "text-gray-400" :
    deltaAbs <= 50  ? "text-green-600 dark:text-green-400" :
    deltaAbs <= 500 ? "text-amber-600 dark:text-amber-400" :
    "text-red-600 dark:text-red-400";

  const DeltaIcon =
    deltaAbs == null ? null :
    deltaAbs <= 50  ? CheckCircle :
    deltaAbs <= 500 ? AlertTriangle :
    XCircle;

  return (
    <div className="border-t border-gray-100 dark:border-gray-700 first:border-t-0">
      <button
        className="w-full flex items-center justify-between py-2.5 px-1 text-sm hover:bg-gray-50 dark:hover:bg-gray-800/40 rounded transition-colors"
        onClick={() => setExpanded(e => !e)}
      >
        <span className="font-medium text-gray-700 dark:text-gray-300 w-10 text-left">
          {MONTH_NAMES[month - 1]}
        </span>

        <div className="flex items-center gap-6 flex-1 justify-end">
          {data ? (
            <>
              <span className="text-gray-500 dark:text-gray-400">
                Forecast: <span className="font-semibold text-gray-700 dark:text-gray-200">{fmt(data.forecasted_close)}</span>
              </span>
              {data.actual_close != null ? (
                <span className="text-gray-500 dark:text-gray-400">
                  Actual: <span className="font-semibold text-gray-700 dark:text-gray-200">{fmt(data.actual_close)}</span>
                </span>
              ) : (
                <span className="text-xs text-gray-400 italic">No checkpoint near month-end</span>
              )}
              {delta != null && (
                <span className={`flex items-center gap-1 font-semibold tabular-nums ${deltaColor}`}>
                  {DeltaIcon && <DeltaIcon size={13} />}
                  {delta >= 0 ? "+" : ""}{fmt(delta)}
                </span>
              )}
            </>
          ) : isLoading ? (
            <span className="text-xs text-gray-400">Loading…</span>
          ) : (
            <span className="text-xs text-gray-400">Click to load</span>
          )}
          <span className="text-gray-400 ml-2">{expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</span>
        </div>
      </button>

      {expanded && data && (
        <div className="pb-3 px-1 space-y-3">
          {/* Matched recurring items */}
          {data.reconcile.matched.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1.5">Matched Recurring</p>
              <div className="space-y-1">
                {data.reconcile.matched.map((m: any) => {
                  const variance = parseFloat(m.variance);
                  const varColor = Math.abs(variance) < 0.01 ? "text-gray-400" : variance > 0 ? "text-green-600" : "text-red-600";
                  return (
                    <div key={m.transaction_id} className="flex items-center justify-between text-xs py-1 px-2 rounded bg-gray-50 dark:bg-gray-800/40">
                      <span className="text-gray-700 dark:text-gray-300">{m.recurring_name}</span>
                      <div className="flex items-center gap-3 tabular-nums">
                        <span className="text-gray-400">expected {fmt(m.expected_amount)}</span>
                        <span className="font-medium text-gray-700 dark:text-gray-200">actual {fmt(m.actual_amount)}</span>
                        {Math.abs(variance) >= 0.01 && (
                          <span className={`font-semibold ${varColor}`}>
                            {variance > 0 ? "+" : ""}{fmt(variance)}
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Unmatched recurring (expected but no transaction) */}
          {data.reconcile.unmatched_recurring.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-amber-600 dark:text-amber-400 uppercase tracking-wide mb-1.5">Missing Transactions</p>
              <div className="space-y-1">
                {data.reconcile.unmatched_recurring.map((r: any) => (
                  <div key={r.recurring_item_id} className="flex items-center justify-between text-xs py-1 px-2 rounded bg-amber-50 dark:bg-amber-900/20">
                    <span className="text-amber-800 dark:text-amber-300">{r.name}</span>
                    <span className="text-amber-700 dark:text-amber-400 font-medium tabular-nums">
                      expected {fmt(r.expected_amount)} on day {r.expected_day}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Unmatched transactions (no recurring item) — with link action */}
          {data.reconcile.unmatched_transactions.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1.5">Unplanned Transactions</p>
              <div className="space-y-1">
                {data.reconcile.unmatched_transactions.map((t: any) => (
                  <div key={t.transaction_id} className="text-xs rounded bg-gray-50 dark:bg-gray-800/40">
                    <div className="flex items-center justify-between py-1 px-2">
                      <span className="text-gray-600 dark:text-gray-300">
                        {new Date(t.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })} · {t.description}
                      </span>
                      <div className="flex items-center gap-2">
                        <span className={`font-medium tabular-nums ${parseFloat(t.amount) < 0 ? "text-red-600" : "text-green-600"}`}>
                          {fmt(t.amount)}
                        </span>
                        <button
                          title="Link to recurring item"
                          onClick={() => { setLinkingTxnId(t.transaction_id); setLinkRecurringId(""); }}
                          className="text-gray-400 hover:text-indigo-500 p-0.5 rounded"
                        >
                          <Link2 size={12} />
                        </button>
                      </div>
                    </div>
                    {linkingTxnId === t.transaction_id && (
                      <div className="flex items-center gap-2 px-2 pb-2">
                        <select
                          className="input py-0.5 text-xs flex-1"
                          value={linkRecurringId}
                          onChange={e => setLinkRecurringId(e.target.value)}
                          autoFocus
                        >
                          <option value="">Select recurring item…</option>
                          {[...(recurringItems as any[])].sort((a, b) => a.name.localeCompare(b.name)).map((r: any) => (
                            <option key={r.id} value={r.id}>{r.name}</option>
                          ))}
                        </select>
                        <button
                          disabled={!linkRecurringId || linkTxnMut.isPending}
                          onClick={() => linkTxnMut.mutate({ txnId: t.transaction_id, recurringItemId: parseInt(linkRecurringId) })}
                          className="btn-primary text-xs px-2 py-0.5"
                        >Link</button>
                        <button onClick={() => setLinkingTxnId(null)} className="btn-secondary text-xs px-2 py-0.5">Cancel</button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {data.reconcile.matched.length === 0 &&
           data.reconcile.unmatched_recurring.length === 0 &&
           data.reconcile.unmatched_transactions.length === 0 && (
            <p className="text-xs text-gray-400 text-center py-2">No actual transactions recorded for this month.</p>
          )}

          {/* Month-end balance anchor */}
          <div className="pt-2 border-t border-gray-100 dark:border-gray-700">
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-xs text-gray-500 dark:text-gray-400">Month-end balance:</span>
              {anchorEditing ? (
                <>
                  <input
                    type="number"
                    step="0.01"
                    className="input py-0.5 w-28 text-xs"
                    placeholder="Actual balance"
                    value={anchorValue}
                    autoFocus
                    onChange={e => setAnchorValue(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === "Enter" && anchorValue) saveAnchorMut.mutate(parseFloat(anchorValue));
                      if (e.key === "Escape") { setAnchorEditing(false); setAnchorValue(""); }
                    }}
                  />
                  <button
                    disabled={!anchorValue || saveAnchorMut.isPending}
                    onClick={() => saveAnchorMut.mutate(parseFloat(anchorValue))}
                    className="btn-primary text-xs px-2 py-0.5"
                  >{saveAnchorMut.isPending ? "Saving…" : "Save"}</button>
                  <button onClick={() => { setAnchorEditing(false); setAnchorValue(""); }} className="btn-secondary text-xs px-2 py-0.5">Cancel</button>
                </>
              ) : (
                <button
                  onClick={() => { setAnchorEditing(true); setAnchorValue(data.actual_close != null ? String(parseFloat(data.actual_close)) : ""); }}
                  className="text-xs text-indigo-500 hover:text-indigo-700 underline"
                >
                  {data.actual_close != null ? fmt(data.actual_close) : "Set actual close →"}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

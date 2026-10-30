import { useQueries } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Landmark } from "lucide-react";
import { accountsApi } from "../api";
import { fmt } from "../lib/utils";
import { maskIfHidden } from "../store/balanceVisibility";

export function PendingBadge() {
  return (
    <span className="shrink-0 text-[10px] uppercase tracking-wide px-1 rounded bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400">
      pending
    </span>
  );
}

/**
 * Each checking account's balance as if its bank-pending items go through:
 * posted current_balance plus the pending snapshot's amounts (negative =
 * money out). Display-only -- nothing here feeds the forecast, the snapshot
 * or any stored figure. Once an item posts, the next sync drops it from the
 * pending snapshot and it is already inside current_balance, so the two
 * never overlap.
 */
export default function CheckingBalancesCard({ accounts, hidden }: { accounts: any[]; hidden: boolean }) {
  const navigate = useNavigate();
  const checking = accounts.filter((a) => a.type === "checking" && a.is_active !== false);
  const pendingQueries = useQueries({
    queries: checking.map((a) => ({
      queryKey: ["account-pending-transactions", a.id],
      queryFn: () => accountsApi.pendingTransactions(a.id),
    })),
  });
  if (checking.length === 0) return null;
  const money = (n: number) => maskIfHidden(hidden, fmt(n));

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2"><Landmark size={16} /> Checking</h3>
        <button onClick={() => navigate("/transactions")} className="text-xs text-indigo-600 hover:underline">Transactions →</button>
      </div>
      <div className="space-y-3">
        {checking.map((a, i) => {
          const pending: any[] = pendingQueries[i]?.data ?? [];
          const posted = parseFloat(a.current_balance);
          const afterPending = posted + pending.reduce((s, p) => s + parseFloat(p.amount), 0);
          return (
            <div key={a.id}>
              <div className="flex items-baseline justify-between gap-4">
                <p className="text-sm font-medium text-gray-900 truncate">{a.name}</p>
                <p className={`text-sm font-bold tabular-nums ${afterPending < 0 ? "text-red-600" : "text-gray-900 dark:text-gray-100"}`}>
                  {money(afterPending)}
                </p>
              </div>
              {pending.length > 0 && (
                <>
                  <p className="text-xs text-gray-400 text-right">
                    Posted {money(posted)} · {pending.length} pending
                  </p>
                  <ul className="mt-1 space-y-0.5">
                    {pending.map((p) => (
                      <li key={p.id} className="flex items-center justify-between gap-2 text-xs text-gray-400">
                        <span className="flex items-center gap-1.5 min-w-0">
                          <span className="whitespace-nowrap">
                            {new Date(p.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                          </span>
                          <span className="truncate">{p.description}</span>
                          <PendingBadge />
                        </span>
                        <span className="tabular-nums whitespace-nowrap">
                          {parseFloat(p.amount) >= 0 ? "+" : "−"}{money(Math.abs(parseFloat(p.amount)))}
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

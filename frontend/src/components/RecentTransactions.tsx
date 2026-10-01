import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { spendingApi } from "../api";
import { fmt } from "../lib/utils";
import { useBalancesHidden, maskIfHidden } from "../store/balanceVisibility";

interface RecentActivityItem {
  id: number;
  uid: string;
  date: string;
  description: string;
  amount: string | number;
  category_name: string | null;
  source: "checking" | "card";
  source_name: string;
}

/** "Sep 29" from an ISO date, parsed at noon so a UTC-negative timezone
 *  can't shift the date back a day (same trick as fmtDate/shortDate
 *  elsewhere in this app), without the year the rest of the Dashboard's
 *  compact cards leave out. */
function shortDate(iso: string): string {
  return new Date(iso + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

const TAG_CLASS = "text-[10px] uppercase tracking-wide px-1 rounded bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 shrink-0";

/**
 * Dashboard "Recent transactions" card: a merged checking + card feed from
 * GET /spending/recent, replacing the old "All Accounts" balances card in
 * the same grid slot. Same exclusions as the Spending page (transfers,
 * card payoffs) so this list never shows something that page would call
 * noise.
 */
export default function RecentTransactions() {
  const navigate = useNavigate();
  const balancesHidden = useBalancesHidden();
  const { data: items = [], isLoading } = useQuery<RecentActivityItem[]>({
    queryKey: ["recent-activity"],
    queryFn: () => spendingApi.recent(10),
  });

  return (
    <div className="card md:col-span-2 2xl:col-span-1">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-gray-900 dark:text-white">Recent transactions</h3>
        <button onClick={() => navigate("/transactions")} className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline">
          See all →
        </button>
      </div>

      {isLoading && <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-4">Loading…</p>}

      {!isLoading && items.length === 0 && (
        <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-4">No recent transactions</p>
      )}

      {!isLoading && items.length > 0 && (
        <div className="divide-y divide-gray-100 dark:divide-gray-700 max-h-80 overflow-y-auto pr-1">
          {items.map((item) => {
            const amount = typeof item.amount === "string" ? parseFloat(item.amount) : item.amount;
            const positive = amount >= 0;
            return (
              <div key={item.uid} className="flex items-center justify-between gap-4 py-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-xs text-gray-400 dark:text-gray-500 shrink-0">{shortDate(item.date)}</span>
                    <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{item.description}</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-1 mt-1">
                    {item.category_name && <span className={TAG_CLASS}>{item.category_name}</span>}
                    <span className={TAG_CLASS}>{item.source_name}</span>
                  </div>
                </div>
                <span
                  className={`text-sm font-bold tabular-nums shrink-0 ${
                    positive ? "text-green-600 dark:text-green-400" : "text-gray-900 dark:text-gray-100"
                  }`}
                >
                  {maskIfHidden(balancesHidden, `${positive ? "+" : "−"}${fmt(Math.abs(amount))}`)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

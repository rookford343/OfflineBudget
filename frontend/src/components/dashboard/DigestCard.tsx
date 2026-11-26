import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import { fmt } from "../../lib/utils";
import { maskIfHidden } from "../../store/balanceVisibility";

interface DigestData {
  total_spent: string;
  categories: any[];
  top_merchants: any[];
}

interface Props {
  title: string;
  digest: DigestData | undefined;
  budgetByCategory: Map<number, any>;
  hidden: boolean;
  emptyText: string;
}

/** Spending digest (weekly or monthly): total, top-5 categories, then top-5 merchants, stacked. */
export function DigestCard({ title, digest, budgetByCategory, hidden, emptyText }: Props) {
  const [categorySortAlpha, setCategorySortAlpha] = useState(false);
  if (!digest) return null;
  return (
    <div className="card">
      <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-1">{title}</h3>
      <p className="text-sm text-gray-500 mb-3">Total spent: <span className="font-semibold text-gray-900 dark:text-gray-100">{maskIfHidden(hidden, fmt(parseFloat(digest.total_spent)))}</span></p>

      <div className="space-y-6">
        {digest.categories.length === 0 && emptyText && (
          <p className="text-sm text-gray-400">{emptyText}</p>
        )}
        {digest.categories.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-2 pb-1 border-b-2 border-line">
              <p className="text-xs font-bold text-accent uppercase tracking-wider">By Category</p>
              <button
                onClick={() => setCategorySortAlpha(v => !v)}
                className="text-[13px] font-medium text-gray-400 dark:text-gray-500 hover:text-accent"
              >
                {categorySortAlpha ? "A–Z" : "Highest first"}
              </button>
            </div>
            <div className="space-y-1.5 text-sm">
              {(categorySortAlpha
                ? [...digest.categories.slice(0, 5)].sort((a: any, b: any) => a.category_name.localeCompare(b.category_name))
                : digest.categories.slice(0, 5)
              ).map((c: any) => {
                const budget = budgetByCategory.get(c.category_id);
                const budgeted = budget ? parseFloat(budget.budgeted) : 0;
                const actual = budget ? parseFloat(budget.actual_total) : 0;
                const pct = budgeted > 0 ? Math.min(100, (actual / budgeted) * 100) : 0;
                const overBudget = budgeted > 0 && actual > budgeted;
                return (
                  <div key={c.category_id} className={`relative rounded overflow-hidden ${budgeted > 0 ? `border-l-2 ${overBudget ? "border-red-500" : "border-accent"}` : ""}`}>
                    {budgeted > 0 && (
                      <div
                        className={`absolute inset-y-0 left-0 ${overBudget ? "bg-red-200/70 dark:bg-red-900/40" : "bg-accent/20"}`}
                        style={{ width: `${pct}%` }}
                      />
                    )}
                    <div className="relative flex justify-between gap-4 px-1.5 py-1 text-gray-600 dark:text-gray-400">
                      <span className="flex items-center gap-1 min-w-0 truncate">
                        {overBudget && <AlertTriangle size={11} className="text-red-500 shrink-0" />}
                        {c.category_name}
                      </span>
                      <span className="tabular-nums shrink-0">{maskIfHidden(hidden, fmt(parseFloat(c.total)))}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {digest.categories.length > 0 && digest.top_merchants.length > 0 && (
          <div>
            <p className="text-xs font-bold text-accent uppercase tracking-wider mb-2 pb-1 border-b-2 border-line">Top Merchants</p>
            <div className="space-y-1.5 text-sm">
              {digest.top_merchants.slice(0, 5).map((m: any) => (
                <div key={m.name} className="flex justify-between gap-4 px-1.5 py-1 text-gray-600 dark:text-gray-400">
                  <span className="truncate">{m.name}</span>
                  <span className="tabular-nums shrink-0">{maskIfHidden(hidden, fmt(parseFloat(m.total)))}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

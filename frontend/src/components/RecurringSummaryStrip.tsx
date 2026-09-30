import { Pencil, Trash2 } from "lucide-react";
import { fmt } from "../lib/utils";

/**
 * Top-of-page Income / Expenses / Left over strip for the Recurring page.
 * Replaces the old Monthly Income/Monthly Expenses stat-card pair and the
 * Monthly Cash Flow card -- both showed the same three numbers this strip
 * now covers in one place, plus this one also lists the income items
 * themselves (the old half-width Income panel's reason to exist).
 */
export default function RecurringSummaryStrip({
  incomeMonthly, expenseMonthly, incomeItems, onEdit, onDelete,
}: {
  incomeMonthly: number;
  expenseMonthly: number;
  incomeItems: any[];
  onEdit: (item: any) => void;
  onDelete: (id: number) => void;
}) {
  const leftOver = incomeMonthly - expenseMonthly;

  return (
    <div className="grid gap-4 items-start md:grid-cols-3">
      <div className="stat-card">
        <span className="stat-label">Income</span>
        <span className="stat-value text-green-600">{fmt(incomeMonthly)}/mo</span>
        {incomeItems.length > 0 && (
          <div className="mt-2 space-y-1.5 border-t border-gray-100 pt-2 dark:border-[#3a4051]">
            {incomeItems.map((item) => (
              <div key={item.id} className="flex items-center justify-between gap-2 text-sm">
                <div className="min-w-0">
                  <p className="truncate text-gray-700 dark:text-[#c4ccd8]">{item.name}</p>
                  <p className="text-xs capitalize text-gray-400">{item.frequency}</p>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <span className="tabular-nums text-green-600">{fmt(item.amount)}</span>
                  <button onClick={() => onEdit(item)} className="btn-ghost p-1" aria-label={`Edit ${item.name}`}>
                    <Pencil size={13} />
                  </button>
                  <button onClick={() => onDelete(item.id)} className="btn-ghost p-1 text-red-500 hover:bg-red-50" aria-label={`Delete ${item.name}`}>
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="stat-card">
        <span className="stat-label">Expenses</span>
        <span className="stat-value text-red-600">{fmt(expenseMonthly)}/mo</span>
      </div>

      <div className="stat-card">
        <span className="stat-label">Left over</span>
        <span className={`stat-value ${leftOver >= 0 ? "text-green-600" : "text-red-600"}`}>
          {leftOver >= 0 ? "+" : ""}{fmt(leftOver)}/mo
        </span>
      </div>
    </div>
  );
}

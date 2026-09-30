import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Pencil, Trash2, ChevronLeft, ChevronRight } from "lucide-react";
import { recurringApi } from "../api";
import { fmt } from "../lib/utils";
import HowCalculated from "./HowCalculated";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** "Jun 10" from an ISO date, parsed at noon so a UTC-negative timezone can't
 *  shift the date back a day. */
function shortDate(iso: string): string {
  return new Date(iso + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/**
 * Top-of-page Income / Expenses / Left over strip for the Recurring page.
 *
 * Backed by GET /recurring/month-summary -- real totals for the switched-to
 * month (every actual occurrence that month, overrides applied), not the
 * smoothed monthly_equivalent breakdown the rest of the page still uses for
 * its "by category" and "ongoing vs temporary" views.
 */
export default function RecurringSummaryStrip({
  incomeItems, onEdit, onDelete,
}: {
  incomeItems: any[];
  onEdit: (item: any) => void;
  onDelete: (id: number) => void;
}) {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);

  const { data: summary } = useQuery<any>({
    queryKey: ["recurring-month-summary", year, month],
    queryFn: () => recurringApi.monthSummary(year, month),
  });

  function shiftMonth(delta: number) {
    let m = month + delta;
    let y = year;
    if (m > 12) { m = 1; y += 1; }
    if (m < 1) { m = 12; y -= 1; }
    setMonth(m);
    setYear(y);
  }

  const incomeById: Record<number, any> = Object.fromEntries(incomeItems.map((i: any) => [i.id, i]));

  const incomeOccurrences = summary?.income_items ?? [];
  const incomeTotal = summary?.income_total ?? 0;
  const monthlyBillsTotal = summary?.monthly_bills_total ?? 0;
  const periodicDue = summary?.periodic_due ?? [];
  const expenseTotal = summary?.expense_total ?? 0;
  const oneOffs = summary?.one_offs ?? [];
  const leftOver = summary?.left_over ?? 0;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-center gap-3">
        <button
          type="button" onClick={() => shiftMonth(-1)} className="btn-ghost p-1"
          aria-label="Previous month"
        >
          <ChevronLeft size={16} />
        </button>
        <span className="text-sm font-semibold text-gray-700 dark:text-gray-300 tabular-nums">
          {MONTHS[month - 1]} {year}
        </span>
        <button
          type="button" onClick={() => shiftMonth(1)} className="btn-ghost p-1"
          aria-label="Next month"
        >
          <ChevronRight size={16} />
        </button>
      </div>

      <div className="grid gap-4 items-start md:grid-cols-3">
        <div className="stat-card">
          <span className="stat-label">Income</span>
          <span className="stat-value text-green-600">{fmt(incomeTotal)}</span>
          {incomeOccurrences.length > 0 && (
            <div className="mt-2 space-y-1.5 border-t border-gray-100 pt-2 dark:border-[#3a4051]">
              {incomeOccurrences.map((occ: any, idx: number) => {
                const item = incomeById[occ.recurring_item_id];
                return (
                  <div key={`${occ.recurring_item_id}-${idx}`} className="flex items-center justify-between gap-2 text-sm">
                    <div className="min-w-0">
                      <p className="truncate text-gray-700 dark:text-[#c4ccd8]">{occ.name}</p>
                      <p className="text-xs text-gray-400">{shortDate(occ.date)}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <span className="tabular-nums text-green-600">{fmt(occ.amount)}</span>
                      {item && (
                        <>
                          <button onClick={() => onEdit(item)} className="btn-ghost p-1" aria-label={`Edit ${occ.name}`}>
                            <Pencil size={13} />
                          </button>
                          <button onClick={() => onDelete(item.id)} className="btn-ghost p-1 text-red-500 hover:bg-red-50" aria-label={`Delete ${occ.name}`}>
                            <Trash2 size={13} />
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="stat-card">
          <span className="stat-label flex items-center gap-1.5">
            Expenses
            <HowCalculated title="Expenses this month" explanations={[summary?.explain?.expense_total]} />
          </span>
          <span className="stat-value text-red-600">{fmt(expenseTotal)}</span>
          <p className="mt-1 text-xs text-gray-400">Monthly bills {fmt(monthlyBillsTotal)}</p>
          {periodicDue.length > 0 && (
            <div className="mt-2 space-y-1.5 border-t border-gray-100 pt-2 dark:border-[#3a4051]">
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Hitting this month</p>
              {periodicDue.map((occ: any, idx: number) => (
                <div key={`${occ.recurring_item_id}-${idx}`} className="flex items-center justify-between gap-2 text-sm">
                  <div className="min-w-0">
                    <p className="truncate text-gray-700 dark:text-[#c4ccd8]">{occ.name}</p>
                    <p className="text-xs text-gray-400">
                      {shortDate(occ.date)}
                      {occ.overridden && (
                        <span className="ml-1 text-indigo-500 dark:text-indigo-300" title="Actual amount, not the modelled estimate">
                          actual
                        </span>
                      )}
                    </p>
                  </div>
                  <span className="shrink-0 tabular-nums text-sm text-red-600">{fmt(occ.amount)}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="stat-card">
          <span className="stat-label flex items-center gap-1.5">
            Left over
            <HowCalculated title="Left over" explanations={[summary?.explain?.left_over]} />
          </span>
          <span className={`stat-value ${leftOver >= 0 ? "text-green-600" : "text-red-600"}`}>
            {leftOver >= 0 ? "+" : ""}{fmt(leftOver)}
          </span>
          {oneOffs.length > 0 && (
            <div className="mt-2 space-y-1.5 border-t border-gray-100 pt-2 dark:border-[#3a4051]">
              {oneOffs.map((occ: any, idx: number) => (
                <div key={`${occ.planned_expense_id}-${idx}`} className="flex items-center justify-between gap-2 text-sm">
                  <div className="min-w-0">
                    <p className="truncate text-gray-700 dark:text-[#c4ccd8]">{occ.name}</p>
                    <p className="text-xs text-gray-400">
                      {shortDate(occ.date)}
                      {occ.settled && <span className="ml-1 text-gray-400">settled</span>}
                    </p>
                  </div>
                  <span className={`shrink-0 tabular-nums text-sm ${occ.direction === "inflow" ? "text-green-600" : "text-red-600"}`}>
                    {occ.direction === "inflow" ? "+" : "−"}{fmt(occ.amount)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { recurringApi, billOverridesApi } from "../api";
import { fmt } from "../lib/utils";
import { Receipt, Check } from "lucide-react";

/** "Mon D" from an ISO date, parsed at noon so a UTC-negative timezone can't
 *  shift the date back a day. */
function shortDate(iso: string): string {
  return new Date(iso + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/**
 * "Bills to confirm": monthly checking expenses with a statement day set,
 * currently inside the window between their statement arriving and their
 * due date, whose real amount hasn't been entered yet for that occurrence.
 * Confirming writes through the existing bill-override feature (the same
 * one the Recurring page's inline $ button uses), so the forecast picks up
 * the real amount for that one due date.
 */
export default function BillsToConfirm() {
  const qc = useQueryClient();
  const { data: bills = [] } = useQuery<any[]>({
    queryKey: ["bills-to-confirm"],
    queryFn: recurringApi.billsToConfirm,
  });
  const [amounts, setAmounts] = useState<Record<number, string>>({});

  const confirmMut = useMutation({
    mutationFn: (data: { recurring_item_id: number; due_date: string; actual_amount: number }) =>
      billOverridesApi.upsert(data),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ["bills-to-confirm"] });
      // Same set the Recurring page's own $ button invalidates (bill
      // overrides + every forecast query key + the budget snapshot), plus
      // the triage badge, which also counts this list.
      qc.invalidateQueries({ queryKey: ["bill-overrides"] });
      qc.invalidateQueries({ queryKey: ["forecast-quarters"] });
      qc.invalidateQueries({ queryKey: ["forecast-multi-year"] });
      qc.invalidateQueries({ queryKey: ["forecast-risk"] });
      qc.invalidateQueries({ queryKey: ["budget-snapshot"] });
      qc.invalidateQueries({ queryKey: ["recurring-triage"] });
      // The confirmed amount replaces an estimate in the month's real totals
      // (Recurring page's summary strip), same as the Recurring page's own
      // inline $ button.
      qc.invalidateQueries({ queryKey: ["recurring-month-summary"] });
      setAmounts((a) => {
        const next = { ...a };
        delete next[variables.recurring_item_id];
        return next;
      });
    },
  });

  if (bills.length === 0) return null;

  return (
    <div className="card">
      <h3 className="font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
        <Receipt size={16} className="text-indigo-500" /> Bills to confirm
      </h3>
      {confirmMut.isError && (
        <p className="text-xs text-red-500 dark:text-red-400 mb-2" role="alert">
          Couldn't save that amount. Try again.
        </p>
      )}
      <div className="space-y-1">
        {bills.map((b: any) => {
          const value = amounts[b.recurring_item_id] ?? "";
          const isThisRowPending =
            confirmMut.isPending && (confirmMut.variables as any)?.recurring_item_id === b.recurring_item_id;
          return (
            <div
              key={b.recurring_item_id}
              className="flex flex-wrap items-center justify-between gap-2 py-2 border-b border-gray-50 dark:border-gray-800 last:border-0"
            >
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{b.name}</p>
                <p className="text-xs text-gray-400">
                  statement ~{shortDate(b.statement_date)} · est. {fmt(b.estimated_amount)}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <input
                  type="number"
                  step="0.01"
                  className="input py-1 text-sm w-24 text-right"
                  placeholder={fmt(b.estimated_amount)}
                  value={value}
                  aria-label={`Actual amount for ${b.name}`}
                  disabled={isThisRowPending}
                  onChange={(e) => setAmounts((a) => ({ ...a, [b.recurring_item_id]: e.target.value }))}
                />
                <button
                  className="btn-primary p-1.5 disabled:opacity-50"
                  aria-label={`Confirm amount for ${b.name}`}
                  title="Confirm this amount"
                  disabled={!value || confirmMut.isPending}
                  onClick={() =>
                    confirmMut.mutate({
                      recurring_item_id: b.recurring_item_id,
                      due_date: b.due_date,
                      actual_amount: parseFloat(value),
                    })
                  }
                >
                  <Check size={14} />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

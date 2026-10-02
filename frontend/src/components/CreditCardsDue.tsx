import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { CreditCard as CardIcon } from "lucide-react";
import { cardsApi } from "../api";
import { fmt, utilColor } from "../lib/utils";
import { useBalancesHidden, maskIfHidden } from "../store/balanceVisibility";

/** "due Mon D" for a card's due_day -- the next occurrence on or after today.
 *  Mirrors backend/services/forecast_engine.py's _next_occurrence_on_or_after
 *  (via summary_generator.py's _due_label), so this card and the daily email
 *  never disagree about which date is next. due_day has no "0 = last day"
 *  convention here (unlike RecurringItem.day_of_month) -- it's always 1-31. */
function nextOccurrenceOnOrAfter(dueDay: number, after: Date): Date {
  const lastDayOfMonth = (y: number, m: number) => new Date(y, m + 1, 0).getDate();
  let y = after.getFullYear();
  let m = after.getMonth();
  const day = Math.min(dueDay, lastDayOfMonth(y, m));
  const candidate = new Date(y, m, day);
  if (candidate >= after) return candidate;
  m += 1;
  if (m > 11) { m = 0; y += 1; }
  const day2 = Math.min(dueDay, lastDayOfMonth(y, m));
  return new Date(y, m, day2);
}

/** Days until due_day's next occurrence, wrapping into next month -- the
 *  same modulo-days-in-month arithmetic as the email's card_rows "due in
 *  Nd" (summary_generator.py's _card_row). JS's `%` can return a negative
 *  result for a negative numerator (Python's can't), so this normalizes. */
function daysUntilDue(dueDay: number, today: Date): number {
  const daysInMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate();
  return (((dueDay - today.getDate()) % daysInMonth) + daysInMonth) % daysInMonth;
}

interface CardRow {
  id: number;
  name: string;
  current_balance: string | number;
  balance_due: string | number;
  pending_charges?: string | number | null;
  due_day: number;
  utilization_pct: number;
  statement_stale_reason?: string | null;
}

/**
 * Dashboard "Credit Cards Due" card: mirrors the daily email's card_rows --
 * balance, utilization, due-in-days and this cycle's spend (current balance
 * minus the statemented balance_due, plus pending charges, floored at 0) --
 * so the two never show different numbers for the same card. GET
 * /credit-cards already carries every field this needs (current_balance,
 * balance_due, pending_charges, utilization_pct, due_day,
 * statement_stale_reason), so there's no backend change here.
 */
export default function CreditCardsDue() {
  const navigate = useNavigate();
  const balancesHidden = useBalancesHidden();
  const { data: cards = [] } = useQuery<CardRow[]>({ queryKey: ["credit-cards"], queryFn: cardsApi.list });
  const today = new Date();

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-gray-900 dark:text-white flex items-center gap-2">
          <CardIcon size={16} /> Credit Cards Due
        </h3>
        <button onClick={() => navigate("/credit-cards")} className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline">
          Manage →
        </button>
      </div>
      {cards.length === 0 ? (
        <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-4">No credit cards added yet</p>
      ) : (
        <div className="space-y-1 max-h-80 overflow-y-auto pr-1">
          {cards.map((c) => {
            const daysOut = daysUntilDue(c.due_day, today);
            const dueInLabel = daysOut === 0 ? "due today" : `due in ${daysOut}d`;
            const dueDateLabel = nextOccurrenceOnOrAfter(c.due_day, today)
              .toLocaleDateString("en-US", { month: "short", day: "numeric" });
            const currentBalance = parseFloat(String(c.current_balance));
            const balanceDue = parseFloat(String(c.balance_due));
            const pending = parseFloat(String(c.pending_charges ?? 0)) || 0;
            const cycleSpend = Math.max(0, currentBalance - balanceDue + pending);
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => navigate("/credit-cards")}
                className="w-full text-left flex items-center justify-between gap-4 py-2 px-1 -mx-1 rounded hover:bg-gray-50 dark:hover:bg-gray-800/50"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{c.name}</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {c.utilization_pct}% used · {dueInLabel}
                  </p>
                  <p className="text-xs text-gray-400 dark:text-gray-500">
                    {maskIfHidden(balancesHidden, fmt(balanceDue))} due {dueDateLabel}
                    {" · "}
                    {maskIfHidden(balancesHidden, fmt(cycleSpend))} spent this cycle
                  </p>
                  {c.statement_stale_reason && (
                    <p className="text-[11px] text-amber-600 dark:text-amber-400 mt-0.5">statement figure may be stale</p>
                  )}
                </div>
                <span className={`text-sm font-bold tabular-nums shrink-0 ${utilColor(c.utilization_pct)}`}>
                  {maskIfHidden(balancesHidden, fmt(currentBalance))}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

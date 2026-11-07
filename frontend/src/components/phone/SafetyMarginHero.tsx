import { fmt } from "../../lib/utils";
import { maskIfHidden } from "../../store/balanceVisibility";
import { friendlyTime } from "../BankSyncStatusLine";

interface Props {
  weekly: number;
  month: number;
  perDay: number;
  pending: { count: number; total: number };
  lastSync: Date | null;
  hidden: boolean;
}

const money = (hidden: boolean, n: number) =>
  maskIfHidden(hidden, `${n < 0 ? "−" : ""}${fmt(Math.abs(n))}`);

/** The phone Dashboard's top number: this week's Safety Margin, with the
 *  month and per-day figures and how fresh the underlying data is. */
export default function SafetyMarginHero({ weekly, month, perDay, pending, lastSync, hidden }: Props) {
  const tone = weekly < 0 ? "text-red-600 dark:text-red-400" : "text-amber-600 dark:text-amber-400";
  return (
    <div className="card bg-gradient-to-br from-emerald-50 to-teal-50 border-emerald-100 dark:from-emerald-950/40 dark:to-teal-950/40 dark:border-emerald-900/50">
      <p className="text-xs font-medium text-gray-500 dark:text-gray-400">Safety Margin (this week)</p>
      <p className={`mt-0.5 text-4xl font-bold tabular-nums ${tone}`}>{money(hidden, weekly)}</p>
      <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
        {money(hidden, month)} this month · {money(hidden, perDay)}/day
      </p>
      <div className="mt-3 space-y-0.5 text-xs text-gray-500 dark:text-gray-400">
        {pending.count > 0 && (
          <p>Includes pending charges on {pending.count} card{pending.count === 1 ? "" : "s"} ({maskIfHidden(hidden, fmt(pending.total))})</p>
        )}
        <p>Last bank sync: {lastSync ? friendlyTime(lastSync.toISOString()) : "not pulled yet"}</p>
      </div>
    </div>
  );
}

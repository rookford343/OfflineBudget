import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { forecastApi, transactionsApi } from "../api";
import { fmt, cx } from "../lib/utils";
import { useBalancesHidden, maskIfHidden } from "../store/balanceVisibility";
import { ChevronLeft, ChevronRight } from "lucide-react";

interface TransactionsCalendarProps {
  accountId: number;
  accountName: string;
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function pad(n: number): string {
  return String(n).padStart(2, "0");
}
function iso(y: number, m: number, d: number): string {
  return `${y}-${pad(m)}-${pad(d)}`;
}

// Month-grid view for a single account's transactions, reusing the same
// forecast engine every other balance display in this app is built on
// (backend/services/forecast_engine.py) for each day's ending balance --
// not re-deriving a running total from raw transactions here, same
// reasoning as the Dashboard's Balance Flow card.
export default function TransactionsCalendar({ accountId, accountName }: TransactionsCalendarProps) {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1); // 1-12
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const balancesHidden = useBalancesHidden();

  const daysInMonth = new Date(year, month, 0).getDate();
  const monthStart = iso(year, month, 1);
  const monthEnd = iso(year, month, daysInMonth);
  const firstWeekday = new Date(year, month - 1, 1).getDay(); // 0=Sun

  const { data: balanceDays = [] } = useQuery<any[]>({
    queryKey: ["txn-calendar-balances", accountId, monthStart, monthEnd],
    queryFn: () => forecastApi.range(accountId, monthStart, monthEnd),
    enabled: !!accountId,
  });
  const { data: monthTxns = [] } = useQuery<any[]>({
    queryKey: ["txn-calendar-txns", accountId, monthStart, monthEnd],
    queryFn: () => transactionsApi.list({ account_id: accountId, start: monthStart, end: monthEnd }),
    enabled: !!accountId,
  });

  const balanceByDate = new Map<string, number>();
  balanceDays.forEach((d: any) => balanceByDate.set(d.date, parseFloat(d.projected_balance)));
  const txnsByDate = new Map<string, any[]>();
  monthTxns.forEach((t: any) => {
    const list = txnsByDate.get(t.date) ?? [];
    list.push(t);
    txnsByDate.set(t.date, list);
  });

  function prevMonth() {
    setSelectedDay(null);
    if (month === 1) { setYear(y => y - 1); setMonth(12); } else { setMonth(m => m - 1); }
  }
  function nextMonth() {
    setSelectedDay(null);
    if (month === 12) { setYear(y => y + 1); setMonth(1); } else { setMonth(m => m + 1); }
  }

  const cells: (number | null)[] = [
    ...Array(firstWeekday).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];
  const todayIso = iso(today.getFullYear(), today.getMonth() + 1, today.getDate());

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-gray-900 dark:text-gray-100">{accountName} — Calendar</h3>
        <div className="flex items-center gap-1">
          <button onClick={prevMonth} className="p-1.5 rounded-full border border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700" aria-label="Previous month">
            <ChevronLeft size={16} />
          </button>
          <span className="px-3 text-sm font-medium text-gray-900 dark:text-gray-100 w-32 text-center">
            {new Date(year, month - 1, 1).toLocaleDateString("en-US", { month: "long", year: "numeric" })}
          </span>
          <button onClick={nextMonth} className="p-1.5 rounded-full border border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700" aria-label="Next month">
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-7 gap-1 text-center text-xs font-medium text-gray-400 mb-1">
        {WEEKDAYS.map(w => <div key={w}>{w}</div>)}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {cells.map((day, i) => {
          if (day === null) return <div key={`empty-${i}`} />;
          const dateStr = iso(year, month, day);
          const dayTxns = txnsByDate.get(dateStr) ?? [];
          const dayNet = dayTxns.reduce((s, t) => s + parseFloat(t.amount), 0);
          const balance = balanceByDate.get(dateStr);
          const isToday = dateStr === todayIso;
          const isSelected = dateStr === selectedDay;
          return (
            <button
              key={dateStr}
              onClick={() => setSelectedDay(s => s === dateStr ? null : dateStr)}
              className={cx(
                "rounded-lg p-1.5 text-left border transition-colors",
                isSelected
                  ? "border-indigo-400 bg-indigo-50 dark:bg-indigo-900/30"
                  : isToday
                    ? "border-indigo-200 dark:border-indigo-700"
                    : "border-transparent hover:bg-gray-50 dark:hover:bg-gray-700/40"
              )}
            >
              <div className="flex items-center justify-between">
                <span className={cx("text-xs", isToday ? "font-bold text-indigo-600 dark:text-indigo-300" : "text-gray-500 dark:text-gray-400")}>{day}</span>
                {dayTxns.length > 0 && (
                  <span className={cx("w-1.5 h-1.5 rounded-full", dayNet >= 0 ? "bg-green-500" : "bg-red-500")} />
                )}
              </div>
              <div className="text-[11px] tabular-nums text-gray-600 dark:text-gray-300 mt-0.5 truncate">
                {balance != null ? maskIfHidden(balancesHidden, fmt(balance)) : ""}
              </div>
            </button>
          );
        })}
      </div>

      {selectedDay && (
        <div className="mt-4 pt-4 border-t border-gray-100 dark:border-gray-700">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
            {new Date(selectedDay + "T12:00:00").toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
          </p>
          {(txnsByDate.get(selectedDay) ?? []).length === 0 ? (
            <p className="text-sm text-gray-400">No transactions this day.</p>
          ) : (
            <div className="space-y-1.5">
              {(txnsByDate.get(selectedDay) ?? []).map((t: any) => (
                <div key={t.id} className="flex items-center justify-between text-sm">
                  <span className="text-gray-700 dark:text-gray-300 truncate">{t.description}</span>
                  <span className={`tabular-nums font-medium shrink-0 ml-3 ${parseFloat(t.amount) >= 0 ? "text-green-600" : "text-red-600"}`}>
                    {parseFloat(t.amount) >= 0 ? "+" : ""}{fmt(t.amount)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

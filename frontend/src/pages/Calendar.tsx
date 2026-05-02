import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { recurringApi } from "../api";
import { fmt } from "../lib/utils";
import { ChevronLeft, ChevronRight, HelpCircle } from "lucide-react";
import HelpPanel from "../components/HelpPanel";

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function lastDayOfMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate();
}

function nextOccurrence(item: any, refYear: number, refMonth: number): Date {
  const dom = item.day_of_month === 0
    ? lastDayOfMonth(refYear, refMonth)
    : Math.min(item.day_of_month, lastDayOfMonth(refYear, refMonth));
  const d = new Date(refYear, refMonth, dom);
  // Apply weekend shift: Sat → Fri, Sun → Fri
  if (d.getDay() === 6) d.setDate(d.getDate() - 1);
  else if (d.getDay() === 0) d.setDate(d.getDate() - 2);
  return d;
}

export default function Calendar() {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth()); // 0-indexed
  const [selectedDay, setSelectedDay] = useState<number | null>(null);
  const [showHelp, setShowHelp] = useState(false);

  const { data: recurring = [] } = useQuery<any[]>({
    queryKey: ["recurring"],
    queryFn: () => recurringApi.list(true),
  });

  function prevMonth() {
    if (month === 0) { setYear(y => y - 1); setMonth(11); }
    else setMonth(m => m - 1);
    setSelectedDay(null);
  }

  function nextMonth() {
    if (month === 11) { setYear(y => y + 1); setMonth(0); }
    else setMonth(m => m + 1);
    setSelectedDay(null);
  }

  // Filter to items that fire in this month (monthly always, yearly only if month matches)
  const activeItems = recurring.filter((r: any) => {
    if (!r.is_active) return false;
    if (r.frequency === "yearly" && r.month_of_year !== month + 1) return false;
    return true;
  });

  // Build day → items map with weekend shift applied
  const dayMap = new Map<number, any[]>();
  activeItems.forEach((r: any) => {
    const d = nextOccurrence(r, year, month);
    // Only include if the shifted date is still in this month
    if (d.getMonth() === month && d.getFullYear() === year) {
      const dom = d.getDate();
      if (!dayMap.has(dom)) dayMap.set(dom, []);
      dayMap.get(dom)!.push(r);
    }
  });

  // Build calendar grid
  const firstDow = new Date(year, month, 1).getDay(); // 0=Sun
  const daysInMonth = lastDayOfMonth(year, month);
  const cells: (number | null)[] = [];
  for (let i = 0; i < firstDow; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);

  const isToday = (d: number) =>
    d === today.getDate() && month === today.getMonth() && year === today.getFullYear();

  // Upcoming 30 days list
  const now = new Date();
  const upcoming = recurring
    .filter((r: any) => r.is_active)
    .flatMap((r: any) => {
      const results = [];
      // Check this month and next
      for (let offset = 0; offset <= 1; offset++) {
        let y = now.getFullYear();
        let m = now.getMonth() + offset;
        if (m > 11) { m -= 12; y += 1; }
        if (r.frequency === "yearly" && r.month_of_year !== m + 1) continue;
        const d = nextOccurrence(r, y, m);
        const diff = (d.getTime() - now.getTime()) / 86400000;
        if (diff >= 0 && diff <= 30) results.push({ ...r, next_date: d });
      }
      return results;
    })
    .sort((a, b) => a.next_date.getTime() - b.next_date.getTime());

  const selectedItems = selectedDay != null ? (dayMap.get(selectedDay) ?? []) : [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-1.5">Bill Calendar <button onClick={() => setShowHelp(true)} className="text-gray-400 hover:text-indigo-500 font-normal"><HelpCircle size={15} /></button></h2>
          <p className="text-sm text-gray-500 dark:text-gray-400">Recurring income and bills by day</p>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={prevMonth} className="btn-secondary p-2"><ChevronLeft size={16} /></button>
          <span className="font-semibold text-gray-900 dark:text-white min-w-[160px] text-center">
            {MONTH_NAMES[month]} {year}
          </span>
          <button onClick={nextMonth} className="btn-secondary p-2"><ChevronRight size={16} /></button>
          <button
            onClick={() => { setYear(today.getFullYear()); setMonth(today.getMonth()); setSelectedDay(null); }}
            className="btn-secondary text-sm px-3"
          >
            Today
          </button>
        </div>
      </div>

      {/* Calendar grid */}
      <div className="card p-0 overflow-hidden">
        {/* Day-of-week headers */}
        <div className="grid grid-cols-7 border-b border-gray-200 dark:border-gray-700">
          {DAYS.map(d => (
            <div key={d} className="py-2 text-center text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
              {d}
            </div>
          ))}
        </div>

        {/* Cells */}
        <div className="grid grid-cols-7">
          {cells.map((d, i) => {
            const items = d != null ? (dayMap.get(d) ?? []) : [];
            const hasExpense = items.some((r: any) => r.type === "expense");
            const hasIncome = items.some((r: any) => r.type === "income");
            const isSelected = d === selectedDay;

            const isWeekend = i % 7 === 0 || i % 7 === 6;
            return (
              <div
                key={i}
                onClick={() => d != null && setSelectedDay(isSelected ? null : d)}
                className={`min-h-[72px] p-2 border-b border-r border-gray-100 dark:border-gray-800 last:border-r-0 transition-colors ${
                  d != null ? "cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/50" : ""
                } ${isSelected ? "bg-indigo-50 dark:bg-indigo-900/20" : isWeekend ? "bg-gray-50 dark:bg-gray-800/30" : ""}`}
              >
                {d != null && (
                  <>
                    <div className="flex items-start justify-between">
                      <span className={`text-sm font-medium w-7 h-7 flex items-center justify-center rounded-full ${
                        isToday(d)
                          ? "bg-indigo-500 text-white"
                          : "text-gray-700 dark:text-gray-300"
                      }`}>
                        {d}
                      </span>
                      <div className="flex gap-1 mt-1">
                        {hasExpense && <span className="w-2 h-2 rounded-full bg-red-400" />}
                        {hasIncome && <span className="w-2 h-2 rounded-full bg-green-500" />}
                      </div>
                    </div>
                    {items.length > 0 && (
                      <div className="mt-1 space-y-0.5">
                        {items.slice(0, 2).map((r: any) => (
                          <p key={r.id} className={`text-xs truncate ${r.type === "income" ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400"}`}>
                            {r.name}
                          </p>
                        ))}
                        {items.length > 2 && (
                          <p className="text-xs text-gray-400">+{items.length - 2} more</p>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Selected day details */}
      {selectedDay != null && selectedItems.length > 0 && (
        <div className="card">
          <h3 className="font-semibold text-gray-900 dark:text-white mb-3">
            {MONTH_NAMES[month]} {selectedDay}, {year}
          </h3>
          <div className="space-y-2">
            {selectedItems.map((r: any) => (
              <div key={r.id} className="flex items-center justify-between py-2 border-b border-gray-100 dark:border-gray-800 last:border-0">
                <div>
                  <p className="text-sm font-medium text-gray-900 dark:text-white">{r.name}</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400 capitalize">{r.frequency} · {r.type}</p>
                </div>
                <span className={`text-sm font-semibold tabular-nums ${r.type === "income" ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                  {r.type === "expense" ? "−" : "+"}{fmt(parseFloat(r.amount))}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Upcoming 30 days */}
      <div className="card">
        <h3 className="font-semibold text-gray-900 dark:text-white mb-3">Next 30 Days</h3>
        {upcoming.length === 0 ? (
          <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-4">No recurring items coming up</p>
        ) : (
          <div className="space-y-2">
            {upcoming.map((r: any, i: number) => {
              const daysUntil = Math.ceil((r.next_date.getTime() - now.getTime()) / 86400000);
              return (
                <div key={`${r.id}-${i}`} className="flex items-center justify-between py-2 border-b border-gray-100 dark:border-gray-800 last:border-0">
                  <div>
                    <p className="text-sm font-medium text-gray-900 dark:text-white">{r.name}</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                      {r.next_date.toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                      {" · "}
                      <span className={daysUntil <= 3 ? "text-red-600 dark:text-red-400 font-medium" : "text-gray-400"}>
                        {daysUntil === 0 ? "Today" : daysUntil === 1 ? "Tomorrow" : `${daysUntil} days`}
                      </span>
                    </p>
                  </div>
                  <span className={`text-sm font-semibold tabular-nums ${r.type === "income" ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                    {r.type === "expense" ? "−" : "+"}{fmt(parseFloat(r.amount))}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
      {showHelp && <HelpPanel title="Bill Calendar" body={"See all recurring bills and income on a monthly calendar.\n\nGreen dots = income · Red dots = bills. Click a day to see details.\n\nItems that fall on Saturday or Sunday are shifted to the preceding Friday.\nWeekend cells are shaded gray. Today is highlighted in indigo.\n\nThe 'Next 30 days' panel below the calendar lists upcoming items sorted by date."} onClose={() => setShowHelp(false)} />}
    </div>
  );
}

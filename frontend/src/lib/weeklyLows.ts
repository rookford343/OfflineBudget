import { fmt } from "./utils";
import { maskIfHidden } from "../store/balanceVisibility";

export type WeeklyLow = {
  start: string;
  end: string;
  amount: string | null;
  date: string | null;
  status: "ok" | "warning" | "danger";
};

export type BarTone = "danger" | "warning" | "accent" | "bar" | "gap";

/** Index of the smallest non-null amount (earliest on ties), or null. */
export function lowestIndex(lows: WeeklyLow[]): number | null {
  let best: number | null = null;
  let bestVal = Infinity;
  lows.forEach((l, i) => {
    if (l.amount == null) return;
    const v = parseFloat(l.amount);
    if (v < bestVal) {
      bestVal = v;
      best = i;
    }
  });
  return best;
}

/** Status color wins over accent; accent marks only an `ok` lowest bar. */
export function barTone(low: WeeklyLow, isLowest: boolean): BarTone {
  if (low.amount == null) return "gap";
  if (low.status === "danger") return "danger";
  if (low.status === "warning") return "warning";
  return isLowest ? "accent" : "bar";
}

function shortDate(iso: string): string {
  return new Date(iso + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** Tooltip / title / aria-label text. Masks the amount when balances are hidden. */
export function barLabel(low: WeeklyLow, hidden: boolean): string {
  const week = `Week of ${shortDate(low.start)}`;
  if (low.amount == null || low.date == null) return `${week}: no forecast low`;
  return `${week}: low ${maskIfHidden(hidden, fmt(parseFloat(low.amount)))} on ${shortDate(low.date)}`;
}

/** First bucket whose start falls in each new month. */
export function monthTicks(lows: WeeklyLow[]): { index: number; label: string }[] {
  const ticks: { index: number; label: string }[] = [];
  let lastMonth = "";
  lows.forEach((l, i) => {
    const month = l.start.slice(0, 7);
    if (month !== lastMonth) {
      lastMonth = month;
      ticks.push({
        index: i,
        label: new Date(l.start + "T12:00:00").toLocaleDateString("en-US", { month: "short" }),
      });
    }
  });
  return ticks;
}

/** Red only below $0; there is no amber state. */
export function safetyMarginTone(weekly: number): "ink" | "danger" {
  return weekly < 0 ? "danger" : "ink";
}

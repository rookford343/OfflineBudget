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

/** Green at $0 or above, red below $0; there is no amber state. */
export function safetyMarginTone(weekly: number): "good" | "danger" {
  return weekly < 0 ? "danger" : "good";
}

/** Green when on pace (>= 0), amber when over pace (< 0). */
export function spendableTone(weekly: number): "good" | "caution" {
  return weekly < 0 ? "caution" : "good";
}

export const CHART_PX = 64;
export const STUB_PX = 4;

/** Top of the chart's $0-based scale: the larger of the biggest low and the cushion (1 if neither is positive). */
export function scaleMaxFor(lows: WeeklyLow[], cushion: number): number {
  let top = Number.isFinite(cushion) ? cushion : 0;
  for (const l of lows) {
    if (l.amount == null) continue;
    const v = parseFloat(l.amount);
    if (v > top) top = v;
  }
  return top > 0 ? top : 1;
}

/** Display-only pixel height of a bar; 0 means "render a gap", negatives get a stub. */
export function barHeightPx(amount: string | null, scaleMax: number): number {
  if (amount == null) return 0;
  const v = parseFloat(amount);
  if (v <= 0) return STUB_PX;
  return Math.max(STUB_PX, Math.round((v / scaleMax) * CHART_PX));
}

/** Display-only distance of the cushion line above the chart baseline. */
export function cushionOffsetPx(cushion: number, scaleMax: number): number {
  return Math.round((Math.max(0, Number.isFinite(cushion) ? cushion : 0) / scaleMax) * CHART_PX);
}

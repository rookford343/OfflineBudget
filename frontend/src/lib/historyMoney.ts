import { fmt } from "./utils";
import { maskIfHidden } from "../store/balanceVisibility";

// Display only: the backend's signed decimal string picks the sign, fmt()
// formats the magnitude. No arithmetic on the figure.
export function signedMoney(hidden: boolean, v: string | null, plus: boolean): string {
  if (v == null) return "";
  const neg = v.startsWith("-");
  const body = maskIfHidden(hidden, fmt(neg ? v.slice(1) : v));
  return `${neg ? "−" : plus ? "+" : ""}${body}`;
}

// A grouped cause's item amount: the figure as the bank listed it, no sign.
export function itemMoney(hidden: boolean, v: string | null): string {
  if (v == null) return "";
  return maskIfHidden(hidden, fmt(v.startsWith("-") ? v.slice(1) : v));
}

// True when two backend decimal strings display as the same signed figure.
// Compares the formatted text; no arithmetic.
export function sameFigure(a: string | null, b: string | null): boolean {
  return signedMoney(false, a, true) === signedMoney(false, b, true);
}

// The statement's top line. The backend sends the net change and the starting
// figure; this only words them. `since` is already formatted ("Nov 7").
export function periodLine(hidden: boolean, delta: string, from: string, since: string): string {
  if (sameFigure(delta, "0")) return `no net change since ${since}`;
  const fell = delta.startsWith("-");
  const size = signedMoney(hidden, fell ? delta.slice(1) : delta, false);
  return `${fell ? "down" : "up"} ${size} since ${since}, from ${signedMoney(hidden, from, false)}`;
}

// A day heading from a YYYY-MM-DD string. Built from its parts: a bare ISO
// date parses as UTC and would land on the wrong local day.
export function dayLabel(day: string, today: Date): string {
  const [y, m, d] = day.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  const isToday = date.getFullYear() === today.getFullYear()
    && date.getMonth() === today.getMonth() && date.getDate() === today.getDate();
  const md = date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return isToday ? `Today, ${md}` : `${date.toLocaleDateString("en-US", { weekday: "short" })}, ${md}`;
}

// One math line's before/after, worded for a line that appeared, vanished or held.
export function mathFigures(hidden: boolean, old: string | null, next: string | null): string {
  if (old == null) return `added, ${signedMoney(hidden, next, false)}`;
  if (next == null) return `removed, was ${signedMoney(hidden, old, false)}`;
  if (sameFigure(old, next)) return `${signedMoney(hidden, old, false)}, no change`;
  return `${signedMoney(hidden, old, false)} → ${signedMoney(hidden, next, false)}`;
}

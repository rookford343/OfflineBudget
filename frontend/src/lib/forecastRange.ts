/**
 * Forecast page range + chart sampling helpers. Pure functions, so the
 * page's date math can be tested without rendering anything.
 */

/** "next4": the current quarter plus the three after it (always shows next
 *  year's Q1 once Q4 starts). "year:2027": one calendar year. "span:3": this
 *  year plus the following years, 3 in total. */
export type RangeKey = "next4" | `year:${number}` | `span:${number}`;

export interface ResolvedRange {
  startYear: number;
  years: number;
  label: string;
  /** Whether a quarter from the fetched span belongs in this range. */
  keep: (q: { year: number; quarter: number }) => boolean;
}

export function currentQuarter(today: Date): { year: number; quarter: number } {
  return { year: today.getFullYear(), quarter: Math.floor(today.getMonth() / 3) + 1 };
}

const qIndex = (q: { year: number; quarter: number }) => q.year * 4 + (q.quarter - 1);

export function resolveRange(key: RangeKey, today: Date): ResolvedRange {
  const thisYear = today.getFullYear();
  if (key === "next4") {
    const start = qIndex(currentQuarter(today));
    const end = start + 3;
    const last = { year: Math.floor(end / 4), quarter: (end % 4) + 1 };
    const first = currentQuarter(today);
    return {
      startYear: thisYear,
      years: last.year > thisYear ? 2 : 1,
      label: `Q${first.quarter} ${first.year} – Q${last.quarter} ${last.year}`,
      keep: (q) => qIndex(q) >= start && qIndex(q) <= end,
    };
  }
  const [kind, raw] = key.split(":");
  const n = parseInt(raw, 10);
  if (kind === "year") return { startYear: n, years: 1, label: String(n), keep: () => true };
  return { startYear: thisYear, years: n, label: `${thisYear}–${thisYear + n - 1}`, keep: () => true };
}

export function rangeOptions(today: Date): { value: RangeKey; label: string }[] {
  const y = today.getFullYear();
  return [
    { value: "next4", label: "Next 4 quarters" },
    { value: `year:${y - 1}`, label: String(y - 1) },
    { value: `year:${y}`, label: String(y) },
    { value: `year:${y + 1}`, label: String(y + 1) },
    { value: "span:2", label: `${y}–${y + 1}` },
    { value: "span:3", label: "3 years" },
    { value: "span:5", label: "5 years" },
  ];
}

/** Target number of plotted points; more than this and the line turns to noise. */
export const MAX_POINTS = 180;

/**
 * Thin a run of days to at most ~MAX_POINTS by keeping the LOWEST-balance day
 * of each equal-size bucket. Keeping the low (not the first day, not an
 * average) means a dip the risk banner warns about is always on the chart.
 * Days before and after `todayIso` are bucketed separately and today itself
 * is always kept, so the Actual and Projected lines meet at today.
 */
export function sampleLows<T extends { date: string; balance: number }>(days: T[], todayIso: string): T[] {
  const past = days.filter((d) => d.date < todayIso);
  const todayDay = days.filter((d) => d.date === todayIso);
  const future = days.filter((d) => d.date > todayIso);
  const k = Math.max(1, Math.ceil(days.length / MAX_POINTS));
  const lows = (run: T[]) => {
    const out: T[] = [];
    for (let i = 0; i < run.length; i += k) {
      out.push(run.slice(i, i + k).reduce((lo, d) => (d.balance < lo.balance ? d : lo)));
    }
    return out;
  };
  return [...lows(past), ...todayDay, ...lows(future)];
}

/** Axis tick values: the first plotted date of each month, thinned to every
 *  `step` months so a multi-year axis stays legible. */
export function monthTicks(dates: string[]): string[] {
  const firsts: string[] = [];
  let lastMonth = "";
  for (const d of dates) {
    const m = d.slice(0, 7);
    if (m !== lastMonth) {
      firsts.push(d);
      lastMonth = m;
    }
  }
  const step = firsts.length > 30 ? 3 : firsts.length > 15 ? 2 : 1;
  return firsts.filter((_, i) => i % step === 0);
}

/** Axis ticks + label style for whatever is plotted. Over ~5 months: one
 *  tick per month ("Jan '27" when the span crosses a year). Shorter (a
 *  zoomed window): about a dozen evenly spaced day ticks ("Nov 12"). */
export function axisTicks(dates: string[]): { ticks: string[]; format: (d: string) => string } {
  if (dates.length === 0) return { ticks: [], format: (d) => d };
  const first = dates[0];
  const last = dates[dates.length - 1];
  const spanDays = (Date.parse(last) - Date.parse(first)) / 86_400_000;
  if (spanDays > 150) {
    const multiYear = first.slice(0, 4) !== last.slice(0, 4);
    return { ticks: monthTicks(dates), format: (d) => tickLabel(d, multiYear) };
  }
  const step = Math.max(1, Math.ceil(dates.length / 12));
  return { ticks: dates.filter((_, i) => i % step === 0), format: (d) => tickLabel(d, false) };
}

/** The first plotted date in each January after the first point: where a
 *  year-boundary line goes. */
export function yearStarts(dates: string[]): string[] {
  const out: string[] = [];
  let lastYear = dates[0]?.slice(0, 4);
  for (const d of dates) {
    const y = d.slice(0, 4);
    if (y !== lastYear) {
      out.push(d);
      lastYear = y;
    }
  }
  return out;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Jan '27" when the chart spans more than one year, "Jan 10" otherwise. */
export function tickLabel(iso: string, multiYear: boolean): string {
  const month = MONTHS[parseInt(iso.slice(5, 7), 10) - 1];
  return multiYear ? `${month} '${iso.slice(2, 4)}` : `${month} ${parseInt(iso.slice(8, 10), 10)}`;
}

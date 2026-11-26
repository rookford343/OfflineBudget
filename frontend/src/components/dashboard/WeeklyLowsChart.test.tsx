import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { WeeklyLowsChart } from "./WeeklyLowsChart";
import { barLabel, type WeeklyLow } from "../../lib/weeklyLows";
import { BALANCE_MASK } from "../../store/balanceVisibility";

// Made-up fixture amounts only (public repo).
const lows: WeeklyLow[] = [
  { start: "2026-12-01", end: "2026-12-07", amount: "1050.00", date: "2026-12-03", status: "ok" },
  { start: "2026-12-08", end: "2026-12-14", amount: "-250.55", date: "2026-12-14", status: "danger" },
];

const caption = (html: string) => html.match(/<p data-testid="bar-caption"[^>]*>([^<]*)<\/p>/)?.[1];

describe("WeeklyLowsChart tap caption", () => {
  test("bars are buttons", () => {
    const html = renderToStaticMarkup(<WeeklyLowsChart lows={lows} hidden={false} />);
    expect(html).toContain('<button type="button"');
  });

  test("no selection: caption is empty", () => {
    const html = renderToStaticMarkup(<WeeklyLowsChart lows={lows} hidden={false} />);
    expect(caption(html) ?? "").toBe("");
  });

  test("selected bar shows its week, amount and date", () => {
    const html = renderToStaticMarkup(<WeeklyLowsChart lows={lows} hidden={false} initialSelected={1} />);
    expect(caption(html)).toBe(barLabel(lows[1], false));
    expect(caption(html)).toContain("Week of Dec 8");
  });

  test("hidden: caption is masked and leaks no amount digits", () => {
    const html = renderToStaticMarkup(<WeeklyLowsChart lows={lows} hidden initialSelected={1} />);
    const text = caption(html)!;
    expect(text).toBe(barLabel(lows[1], true));
    expect(text).toContain(BALANCE_MASK);
    expect(text).not.toMatch(/250|\$/);
  });
});

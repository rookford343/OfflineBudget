import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { WeeklyLowsChart } from "./WeeklyLowsChart";
import { barHeightPx, barLabel, cushionOffsetPx, scaleMaxFor, type WeeklyLow } from "../../lib/weeklyLows";
import { BALANCE_MASK } from "../../store/balanceVisibility";

// Made-up fixture amounts only (public repo).
const lows: WeeklyLow[] = [
  { start: "2026-12-01", end: "2026-12-07", amount: "1050.00", date: "2026-12-03", status: "ok" },
  { start: "2026-12-08", end: "2026-12-14", amount: "-250.55", date: "2026-12-14", status: "danger" },
];

const caption = (html: string) => html.match(/<p data-testid="bar-caption"[^>]*>([^<]*)<\/p>/)?.[1];

describe("WeeklyLowsChart tap caption", () => {
  test("bars are buttons", () => {
    const html = renderToStaticMarkup(<WeeklyLowsChart lows={lows} hidden={false} cushion={500} />);
    expect(html).toContain('<button type="button"');
  });

  test("no selection: caption is empty", () => {
    const html = renderToStaticMarkup(<WeeklyLowsChart lows={lows} hidden={false} cushion={500} />);
    expect(caption(html) ?? "").toBe("");
  });

  test("selected bar shows its week, amount and date", () => {
    const html = renderToStaticMarkup(<WeeklyLowsChart lows={lows} hidden={false} cushion={500} initialSelected={1} />);
    expect(caption(html)).toBe(barLabel(lows[1], false));
    expect(caption(html)).toContain("Week of Dec 8");
  });

  test("hidden: caption is masked and leaks no amount digits", () => {
    const html = renderToStaticMarkup(<WeeklyLowsChart lows={lows} hidden cushion={500} initialSelected={1} />);
    const text = caption(html)!;
    expect(text).toBe(barLabel(lows[1], true));
    expect(text).toContain(BALANCE_MASK);
    expect(text).not.toMatch(/250|\$/);
  });
});

describe("WeeklyLowsChart geometry and order", () => {
  const render = (hidden = false) =>
    renderToStaticMarkup(
      <div>
        <WeeklyLowsChart lows={lows} hidden={hidden} cushion={500} initialSelected={0} />
        <p data-testid="after-chart">Lowest</p>
      </div>,
    );

  test("cushion line sits at the scaled offset and carries no text", () => {
    const html = render();
    const m = html.match(/<div[^>]*data-testid="cushion-line"[^>]*>([^<]*)<\/div>/);
    expect(m).not.toBeNull();
    expect(m![1]).toBe("");
    const off = cushionOffsetPx(500, scaleMaxFor(lows, 500));
    expect(m![0]).toContain(`bottom:${off}px`);
    expect(html.match(/data-testid="cushion-line"/g)?.length).toBe(1);
    // spans exactly the bar row (n bars of 40px + gaps of 6px), capped at the chart width
    expect(m![0]).toContain(`width:min(100%, ${lows.length * 40 + (lows.length - 1) * 6}px)`);
    expect(m![0]).not.toContain("inset-x-0");
  });

  test("bar heights come from barHeightPx", () => {
    const html = render();
    const max = scaleMaxFor(lows, 500);
    for (const l of lows) expect(html).toContain(`height:${barHeightPx(l.amount, max)}px`);
    expect(html).toContain("height:4px");
  });

  test("month ticks precede the caption, which precedes later content", () => {
    const html = render();
    const t = html.indexOf('data-testid="month-ticks"');
    const c = html.indexOf('data-testid="bar-caption"');
    const a = html.indexOf('data-testid="after-chart"');
    expect(t).toBeGreaterThan(-1);
    expect(t).toBeLessThan(c);
    expect(c).toBeLessThan(a);
  });

  test("hidden: no amount digits leak", () => {
    const html = render(true).replace(/ class="[^"]*"/g, "").replace(/ style="[^"]*"/g, "");
    expect(html).not.toMatch(/1050|250|\$/);
  });
});

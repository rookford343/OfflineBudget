import { barLabel, barTone, lowestIndex, monthTicks, type BarTone, type WeeklyLow } from "../../lib/weeklyLows";

const TONE_CLASS: Record<BarTone, string> = {
  danger: "bg-red-500 dark:bg-red-400",
  warning: "bg-warn",
  accent: "bg-accent",
  bar: "bg-bar",
  gap: "",
};

const CHART_PX = 48;
const MIN_BAR_PX = 6;

export function WeeklyLowsChart({ lows, hidden }: { lows: WeeklyLow[]; hidden: boolean }) {
  if (lows.length === 0) return null;
  const amounts = lows.filter((l) => l.amount != null).map((l) => parseFloat(l.amount as string));
  const min = amounts.length ? Math.min(...amounts) : 0;
  const max = amounts.length ? Math.max(...amounts) : 0;
  const lowest = lowestIndex(lows);
  const heightFor = (amount: string) => {
    if (max === min) return CHART_PX;
    const frac = (parseFloat(amount) - min) / (max - min);
    return Math.round(MIN_BAR_PX + frac * (CHART_PX - MIN_BAR_PX));
  };
  const ticks = monthTicks(lows);

  return (
    <div>
      <div className="flex items-end gap-1" style={{ height: CHART_PX }}>
        {lows.map((l, i) => {
          const tone = barTone(l, i === lowest);
          const label = barLabel(l, hidden);
          if (tone === "gap" || l.amount == null) {
            return <div key={l.start} className="flex-1 h-full" title={label} aria-label={label} role="img" />;
          }
          return (
            <div
              key={l.start}
              role="img"
              className="flex-1 h-full flex items-end"
              title={label}
              aria-label={label}
            >
              <div className={`w-full rounded-sm ${TONE_CLASS[tone]}`} style={{ height: heightFor(l.amount) }} />
            </div>
          );
        })}
      </div>
      <div className="relative mt-1 h-4 text-[13px] text-muted">
        {ticks.map((t) => (
          <span
            key={t.index}
            className="absolute"
            style={{ left: `${(t.index / lows.length) * 100}%` }}
          >
            {t.label}
          </span>
        ))}
      </div>
    </div>
  );
}

import { useState } from "react";
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

/** `initialSelected` exists so static-render tests can show the tapped state. */
export function WeeklyLowsChart({
  lows,
  hidden,
  initialSelected,
}: {
  lows: WeeklyLow[];
  hidden: boolean;
  initialSelected?: number;
}) {
  const [selected, setSelected] = useState<number | null>(initialSelected ?? null);
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
            <button
              type="button"
              key={l.start}
              className="flex-1 h-full flex items-end"
              title={label}
              aria-label={label}
              onClick={() => setSelected(i)}
              onFocus={() => setSelected(i)}
            >
              <div className={`w-full rounded-sm ${TONE_CLASS[tone]}`} style={{ height: heightFor(l.amount) }} />
            </button>
          );
        })}
      </div>
      <p data-testid="bar-caption" className="text-[13px] text-muted mt-1 min-h-[1.25rem]">
        {selected != null && lows[selected] ? barLabel(lows[selected], hidden) : ""}
      </p>
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

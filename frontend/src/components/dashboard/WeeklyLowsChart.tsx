import { useState } from "react";
import {
  barHeightPx,
  barLabel,
  barTone,
  CHART_PX,
  cushionOffsetPx,
  lowestIndex,
  monthTicks,
  scaleMaxFor,
  type BarTone,
  type WeeklyLow,
} from "../../lib/weeklyLows";

const TONE_CLASS: Record<BarTone, string> = {
  danger: "bg-red-500 dark:bg-red-400",
  warning: "bg-warn",
  accent: "bg-accent",
  bar: "bg-bar",
  gap: "",
};

/** `initialSelected` exists so static-render tests can show the tapped state. */
export function WeeklyLowsChart({
  lows,
  hidden,
  cushion,
  initialSelected,
}: {
  lows: WeeklyLow[];
  hidden: boolean;
  cushion: number;
  initialSelected?: number;
}) {
  const [selected, setSelected] = useState<number | null>(initialSelected ?? null);
  if (lows.length === 0) return null;
  const scaleMax = scaleMaxFor(lows, cushion);
  const lowest = lowestIndex(lows);
  const ticks = monthTicks(lows);

  const tickAt = new Map(ticks.map((t) => [t.index, t.label]));

  return (
    <div>
      <div className="relative">
        <div className="flex items-end justify-start gap-[6px]" style={{ height: CHART_PX }}>
          {lows.map((l, i) => {
            const tone = barTone(l, i === lowest);
            const label = barLabel(l, hidden);
            if (tone === "gap" || l.amount == null) {
              return <div key={l.start} className="w-full max-w-[40px] flex-1 h-full" title={label} aria-label={label} role="img" />;
            }
            return (
              <button
                type="button"
                key={l.start}
                className="w-full max-w-[40px] flex-1 h-full flex items-end"
                title={label}
                aria-label={label}
                onClick={() => setSelected(i)}
                onFocus={() => setSelected(i)}
              >
                <div className={`w-full rounded-sm ${TONE_CLASS[tone]}`} style={{ height: barHeightPx(l.amount, scaleMax) }} />
              </button>
            );
          })}
        </div>
        <div
          data-testid="cushion-line"
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 border-t border-dashed border-muted opacity-70"
          style={{ bottom: cushionOffsetPx(cushion, scaleMax) }}
        />
      </div>
      <div data-testid="month-ticks" className="mt-1 flex justify-start gap-[6px] h-4 text-[13px] text-muted">
        {lows.map((l, i) => (
          <div key={l.start} className="relative w-full max-w-[40px] flex-1 min-w-0">
            {tickAt.has(i) && <span className="absolute left-0 whitespace-nowrap">{tickAt.get(i)}</span>}
          </div>
        ))}
      </div>
      <p data-testid="bar-caption" className="text-[13px] text-muted mt-1 min-h-[1.25rem]">
        {selected != null && lows[selected] ? barLabel(lows[selected], hidden) : ""}
      </p>
    </div>
  );
}

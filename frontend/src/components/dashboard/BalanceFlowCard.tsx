import { fmt } from "../../lib/utils";
import { maskIfHidden } from "../../store/balanceVisibility";
import { TrendingUp } from "lucide-react";
import { AreaChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

interface Props {
  balanceFlow: any[];
  lastMonthFlow: any[];
  baseline: any;
  flowFigures: any;
  lastMonthRange: { start: string; end: string };
  monthStart: string;
  todayStr: string;
  isDark: boolean;
  balancesHidden: boolean;
  /** Stretch to the full height of the grid row (xwide layout only). */
  fill?: boolean;
}

/** Balance Flow: this month's projected balance against the saved forecast
 *  (or last month). All figures are computed in Dashboard and passed in. */
export function BalanceFlowCard({ balanceFlow, lastMonthFlow, baseline, flowFigures, lastMonthRange, monthStart, todayStr, isDark, balancesHidden, fill = false }: Props) {
  if (!(balanceFlow.length > 0 || lastMonthFlow.length > 0 || !!baseline?.points)) return null;
  // Reference line: the saved start-of-month forecast when there is
  // one, otherwise last month's actuals. Keyed by day-of-month either
  // way so both lines share an X position.
  const reference: any[] = baseline?.points ?? lastMonthFlow;
  const refIsForecast = !!baseline?.points;
  const byDay = new Map<number, { day: number; thisMonth?: number; reference?: number }>();
  for (const e of reference) {
    const day = parseInt(e.date.slice(-2), 10);
    byDay.set(day, { day, reference: parseFloat(e.projected_balance) });
  }
  for (const e of balanceFlow) {
    const day = parseInt(e.date.slice(-2), 10);
    const row = byDay.get(day) ?? { day };
    row.thisMonth = parseFloat(e.projected_balance);
    byDay.set(day, row);
  }
  const chartData = [...byDay.values()].sort((a, b) => a.day - b.day);

  const last = balanceFlow.length ? parseFloat(balanceFlow[balanceFlow.length - 1].projected_balance) : null;

  const lastMonthName = new Date(lastMonthRange.start + "T12:00:00").toLocaleDateString("en-US", { month: "long" });
  const thisMonthName = new Date(monthStart + "T12:00:00").toLocaleDateString("en-US", { month: "long" });
  const todayDay = parseInt(todayStr.slice(-2), 10);
  const sameDayRef = reference.find((e: any) => parseInt(e.date.slice(-2), 10) === todayDay);
  const refToday = sameDayRef ? parseFloat(sameDayRef.projected_balance) : null;

  // Headline: drift from forecast when there's a baseline, otherwise
  // the month-to-date change it has always shown.
  const rawDelta = refIsForecast ? flowFigures?.drift_from_forecast : flowFigures?.month_to_date_change;
  const delta = rawDelta != null ? parseFloat(rawDelta) : null;
  const sameDayPct = refToday != null && last != null && refToday !== 0
    ? ((last - refToday) / Math.abs(refToday)) * 100
    : null;
  const refName = refIsForecast ? "Forecast" : lastMonthName;
  const savedOn = refIsForecast
    ? new Date(baseline.taken_on + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })
    : null;

  const lineColor = isDark ? "#2dd4bf" : "#0f766e";
  const priorLineColor = isDark ? "#5b6577" : "#9ca3af";
  return (
    <div className={fill ? "card h-full flex flex-col" : "card"}>
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2"><TrendingUp size={16} className="text-accent" /> Balance Flow</h3>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
            {refIsForecast
              ? <>{thisMonthName} so far, vs. forecast from {savedOn}</>
              : <>{thisMonthName} so far, vs. all of {lastMonthName}</>}
          </p>
        </div>
        {delta != null && (
          <span className={`text-xl font-bold tabular-nums ${delta >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
            {maskIfHidden(balancesHidden, `${delta >= 0 ? "+" : "−"}${fmt(Math.abs(delta))}`)}
          </span>
        )}
      </div>
      <div className={fill ? "flex-1 min-h-[220px]" : undefined}>
      <ResponsiveContainer width="100%" height={fill ? "100%" : 200}>
        <AreaChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
          <defs>
            <linearGradient id="balanceFlowGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={lineColor} stopOpacity={0.18} />
              <stop offset="95%" stopColor={lineColor} stopOpacity={0.01} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={isDark ? "#3a4051" : "#e5e7eb"} />
          <XAxis dataKey="day" tick={{ fontSize: 11, fill: isDark ? "#8f99a8" : "#6b7280" }} />
          <YAxis tick={{ fontSize: 11, fill: isDark ? "#8f99a8" : "#6b7280" }} tickFormatter={(v: number) => balancesHidden ? "•••" : fmt(v)} width={balancesHidden ? 40 : 70} domain={["auto", "auto"]} />
          <Tooltip
            contentStyle={{ backgroundColor: isDark ? "#2a2f3d" : "#ffffff", border: `1px solid ${isDark ? "#3a4051" : "#e5e7eb"}`, borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: isDark ? "#c4ccd8" : "#111827" }}
            formatter={(v: number, name: string) => [maskIfHidden(balancesHidden, fmt(v)), name === "thisMonth" ? thisMonthName : refName]}
            labelFormatter={(d: number) => `Day ${d}`}
          />
          <Area type="monotone" dataKey="thisMonth" stroke={lineColor} strokeWidth={2} fill="url(#balanceFlowGradient)" dot={false} connectNulls animationDuration={700} animationEasing="ease-out" />
          <Line type="monotone" dataKey="reference" stroke={priorLineColor} strokeWidth={1.5} strokeDasharray="4 3" dot={false} connectNulls isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
      </div>
      {sameDayRef && sameDayPct != null && (
        <p className="text-xs text-gray-400 mt-2">
          {refIsForecast ? <>Forecast for day {todayDay}: </> : <>In {lastMonthName} on day {todayDay}: </>}
          {maskIfHidden(balancesHidden, fmt(refToday!))}
          {" "}({sameDayPct >= 0 ? "+" : ""}{sameDayPct.toFixed(1)}%)
        </p>
      )}
    </div>
  );
}

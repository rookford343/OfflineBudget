import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { spendingApi, accountsApi, cardsApi, analyticsApi } from "../api";
import { api } from "../api/client";
import { sankey as d3Sankey, sankeyLinkHorizontal, sankeyLeft } from "d3-sankey";
import { fmt, firstOfMonth, today, quickRange } from "../lib/utils";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, ReferenceLine,
  AreaChart, Area, Sector,
} from "recharts";
import { ChevronDown, ChevronRight, HelpCircle } from "lucide-react";
import HelpPanel from "../components/HelpPanel";

function isDarkMode(): boolean {
  return document.documentElement.classList.contains("dark");
}

function chartTheme() {
  const dark = isDarkMode();
  return {
    grid:    dark ? "#2c3040" : "#e5e7eb",
    tick:    dark ? "#6e7888" : "#6b7280",
    refLine: dark ? "#4a5568" : "#9ca3af",
    tooltip: dark ? "#1f2330" : "#ffffff",
    tooltipBorder: dark ? "#2c3040" : "#e5e7eb",
    tooltipText: dark ? "#c4ccd8" : "#111827",
    tooltipMuted: dark ? "#6e7888" : "#6b7280",
    barFill: dark ? "#818cf8" : "#6366f1",
  };
}

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const YEAR_COLORS = ["#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"];

export default function Spending() {
  const [showHelp, setShowHelp] = useState(false);
  const [activeTab, setActiveTab] = useState<"overview" | "trends" | "flow" | "tax">("overview");
  const [taxYear, setTaxYear] = useState(new Date().getFullYear());
  const [sankeyYear, setSankeyYear] = useState(new Date().getFullYear());
  const [sankeyMonth, setSankeyMonth] = useState(new Date().getMonth() + 1);
  const [start, setStart] = useState(firstOfMonth());
  const [end, setEnd] = useState(today());
  const [expanded, setExpanded] = useState<number | null>(null);
  const [sourceKey, setSourceKey] = useState<string>("all");
  const [catFilter, setCatFilter] = useState<Set<number> | null>(null);
  const [activeIndex, setActiveIndex] = useState(-1);

  const { data: accounts = [] } = useQuery({ queryKey: ["accounts"], queryFn: accountsApi.list });
  const { data: cards = [] } = useQuery({ queryKey: ["cards"], queryFn: cardsApi.list });
  const checkingAccounts = accounts.filter((a: any) => a.type === "checking");

  const selectedAccountId = sourceKey.startsWith("account-") ? parseInt(sourceKey.replace("account-", "")) : undefined;
  const selectedCardId    = sourceKey.startsWith("card-")    ? parseInt(sourceKey.replace("card-", ""))    : undefined;

  const { data: overview, isLoading } = useQuery({
    queryKey: ["spending-overview", start, end, selectedAccountId, selectedCardId],
    queryFn: () => spendingApi.byCategory(start, end, selectedAccountId, selectedCardId),
    enabled: !!start && !!end,
  });

  const { data: monthly = [] } = useQuery({
    queryKey: ["spending-monthly", start, end, selectedAccountId, selectedCardId],
    queryFn: () => spendingApi.monthly(start, end, selectedAccountId, selectedCardId),
    enabled: !!start && !!end,
  });

  const { data: yearlyTrends = [] } = useQuery({
    queryKey: ["yearly-trends"],
    queryFn: () => analyticsApi.yearlyTrends(3),
    enabled: activeTab === "trends",
  });

  const { data: rollingMonthly = [] } = useQuery({
    queryKey: ["rolling-monthly"],
    queryFn: () => analyticsApi.rollingMonthly(24),
    enabled: activeTab === "trends",
  });

  const { data: sankeyData } = useQuery({
    queryKey: ["sankey", sankeyYear, sankeyMonth],
    queryFn: () => spendingApi.sankey(sankeyYear, sankeyMonth),
    enabled: activeTab === "flow",
  });

  const { data: monthlyByCat = [] } = useQuery({
    queryKey: ["spending-monthly-by-cat", start, end, selectedAccountId, selectedCardId],
    queryFn: () => spendingApi.monthlyByCategory(start, end, selectedAccountId, selectedCardId),
    enabled: !!start && !!end,
  });

  // All unique top-level categories that appear in the monthly-by-cat data
  const allTopCats = useMemo(() => {
    const seen = new Map<number, { id: number; name: string; color: string }>();
    monthlyByCat.forEach((row: any) => {
      row.categories.forEach((c: any) => {
        if (!seen.has(c.category_id))
          seen.set(c.category_id, { id: c.category_id, name: c.category_name, color: c.color });
      });
    });
    return Array.from(seen.values());
  }, [monthlyByCat]);

  const visibleCatIds: Set<number> = catFilter ?? new Set(allTopCats.map(c => c.id));

  // Recharts data for total monthly bars
  const barData = monthly.map((m: any) => ({
    month: m.month,
    total: parseFloat(m.total),
  }));
  const avg = barData.length > 1 ? barData.reduce((s: number, d: any) => s + d.total, 0) / barData.length : 0;

  // Recharts data for category stacked bars
  const stackedData = useMemo(() => {
    if (!monthlyByCat.length) return [];
    return monthlyByCat.map((row: any) => {
      const entry: Record<string, number | string> = { month: row.month };
      row.categories.forEach((c: any) => {
        if (visibleCatIds.has(c.category_id)) entry[c.category_name] = parseFloat(c.total);
      });
      return entry;
    });
  }, [monthlyByCat, visibleCatIds]);

  // Pie chart data
  const pieData = (overview?.categories ?? [])
    .filter((c: any) => parseFloat(c.actual) > 0)
    .map((c: any) => ({ name: c.category_name, value: parseFloat(c.actual), color: c.color }));

  const ct = chartTheme();

  function TooltipBox({ label, rows }: { label?: string; rows: { name: string; value: number; color?: string }[] }) {
    return (
      <div style={{ background: ct.tooltip, border: `1px solid ${ct.tooltipBorder}`, color: ct.tooltipText }}
        className="rounded-xl shadow-lg py-2 px-3 text-sm">
        {label && <p style={{ color: ct.tooltipMuted }} className="text-xs mb-1">{label}</p>}
        {rows.map(r => (
          <div key={r.name} className="flex items-center gap-2">
            {r.color && <div className="w-2 h-2 rounded-full shrink-0" style={{ background: r.color }} />}
            <span>{r.name}:</span>
            <span className="font-semibold ml-auto pl-4">{fmt(r.value)}</span>
          </div>
        ))}
      </div>
    );
  }

  const TotalBarTooltip = ({ active, payload, label }: any) =>
    active && payload?.length ? (
      <TooltipBox label={label} rows={[{ name: "Spending", value: payload[0].value }]} />
    ) : null;

  const StackedTooltip = ({ active, payload, label }: any) =>
    active && payload?.length ? (
      <TooltipBox
        label={label}
        rows={payload.map((p: any) => ({ name: p.name, value: p.value, color: p.fill }))}
      />
    ) : null;

  const PieTooltip = ({ active, payload }: any) =>
    active && payload?.length ? (
      <TooltipBox rows={[{ name: payload[0].name, value: payload[0].value, color: payload[0].payload.color }]} />
    ) : null;

  function renderActiveShape(props: any) {
    const { cx, cy, innerRadius, outerRadius, startAngle, endAngle, fill, payload, value } = props;
    const total = pieData.reduce((s: number, d: any) => s + d.value, 0);
    const pctStr = total > 0 ? `${((value / total) * 100).toFixed(1)}%` : "";
    return (
      <g>
        <Sector cx={cx} cy={cy} innerRadius={innerRadius} outerRadius={outerRadius + 8} startAngle={startAngle} endAngle={endAngle} fill={fill} />
        <text x={cx} y={cy - 10} textAnchor="middle" fill={isDarkMode() ? "#c4ccd8" : "#111827"} fontSize={13} fontWeight={600}>{payload.name}</text>
        <text x={cx} y={cy + 8} textAnchor="middle" fill={isDarkMode() ? "#c4ccd8" : "#111827"} fontSize={12}>{fmt(value)}</text>
        <text x={cx} y={cy + 24} textAnchor="middle" fill={isDarkMode() ? "#6e7888" : "#6b7280"} fontSize={11}>{pctStr}</text>
      </g>
    );
  }

  function ProgressBar({ actual, budgeted }: { actual: number; budgeted: number }) {
    if (budgeted === 0) return null;
    const pct = Math.min(100, (actual / budgeted) * 100);
    return (
      <div className="mt-1 w-full">
        <div className="progress-bar">
          <div className={`progress-fill ${pct > 100 ? "bg-red-500" : pct > 80 ? "bg-amber-500" : "bg-green-500"}`}
            style={{ width: `${pct}%` }} />
        </div>
      </div>
    );
  }

  function toggleCat(id: number) {
    const current = catFilter ?? new Set(allTopCats.map(c => c.id));
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    // If all are now checked, reset to null (all)
    if (next.size === allTopCats.length) setCatFilter(null);
    else setCatFilter(next);
  }

  const trendBarData = useMemo(() => {
    if (!yearlyTrends.length) return [];
    return MONTH_NAMES.map((name, i) => {
      const entry: Record<string, number | string> = { month: name };
      (yearlyTrends as any[]).forEach((yr: any) => {
        entry[String(yr.year)] = parseFloat(yr.months[String(i + 1)] ?? "0");
      });
      return entry;
    });
  }, [yearlyTrends]);

  const rollingBarData = useMemo(() => {
    return (rollingMonthly as any[]).map((r: any) => ({
      month: r.month,
      total: parseFloat(r.total),
    }));
  }, [rollingMonthly]);

  return (
    <div className="space-y-6">
      {/* Header + controls */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-[#c4ccd8] flex items-center gap-1.5">Spending <button onClick={() => setShowHelp(true)} className="text-gray-400 hover:text-indigo-500 font-normal"><HelpCircle size={15} /></button></h2>
          <p className="text-sm text-gray-500 dark:text-[#6e7888]">Across checking + all credit cards</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <select className="input w-auto" value={sourceKey} onChange={e => { setSourceKey(e.target.value); setCatFilter(null); }}>
            <option value="all">All Sources</option>
            {checkingAccounts.map((a: any) => <option key={`account-${a.id}`} value={`account-${a.id}`}>{a.name}</option>)}
            {cards.map((c: any) => <option key={`card-${c.id}`} value={`card-${c.id}`}>{c.name}</option>)}
          </select>
          <div className="flex gap-1">
            {([["Mo", "month"], ["3 Mo", "3months"], ["YTD", "ytd"], ["Last Yr", "lastyear"]] as const).map(([label, p]) => (
              <button key={p} type="button" className="px-2 py-1 text-xs rounded-md bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 hover:text-indigo-600 dark:hover:text-indigo-400" onClick={() => { const r = quickRange(p); setStart(r.start); setEnd(r.end); }}>{label}</button>
            ))}
          </div>
          <input type="date" className="input w-auto" value={start} onChange={e => setStart(e.target.value)} />
          <span className="self-center text-gray-400 dark:text-[#4a5568]">→</span>
          <input type="date" className="input w-auto" value={end} onChange={e => setEnd(e.target.value)} />
        </div>
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1 border-b border-gray-200 dark:border-gray-700">
        {(["overview", "trends", "flow", "tax"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium capitalize border-b-2 transition-colors ${
              activeTab === tab
                ? "border-indigo-500 text-indigo-600 dark:text-indigo-400"
                : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300"
            }`}
          >
            {tab === "flow" ? "Flow" : tab === "tax" ? "Tax Export" : tab}
          </button>
        ))}
      </div>

      {/* Trends tab */}
      {activeTab === "trends" && (
        <div className="space-y-6">
          {trendBarData.length > 0 && yearlyTrends.length > 0 && (
            <div className="card">
              <h3 className="font-semibold text-gray-900 dark:text-[#c4ccd8] mb-4">Year-Over-Year Monthly Spending</h3>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={trendBarData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
                  <XAxis dataKey="month" tick={{ fontSize: 11, fill: ct.tick }} axisLine={{ stroke: ct.grid }} tickLine={false} />
                  <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11, fill: ct.tick }} axisLine={false} tickLine={false} />
                  <Tooltip content={({ active, payload, label }) => active && payload?.length ? (
                    <TooltipBox label={label} rows={payload.map((p: any) => ({ name: p.dataKey, value: p.value, color: p.fill }))} />
                  ) : null} cursor={{ fill: isDarkMode() ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)" }} />
                  <Legend formatter={(v) => <span style={{ color: ct.tick }} className="text-sm">{v}</span>} />
                  {(yearlyTrends as any[]).map((yr: any, i: number) => (
                    <Bar key={yr.year} dataKey={String(yr.year)} fill={YEAR_COLORS[i % YEAR_COLORS.length]} radius={[3, 3, 0, 0]} name={String(yr.year)} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {rollingBarData.length > 0 && (
            <div className="card">
              <h3 className="font-semibold text-gray-900 dark:text-[#c4ccd8] mb-4">24-Month Spending Trend</h3>
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={rollingBarData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="spendingTrendGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#6366f1" stopOpacity={0.20} />
                      <stop offset="95%" stopColor="#6366f1" stopOpacity={0.00} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
                  <XAxis dataKey="month" tick={{ fontSize: 10, fill: ct.tick }} interval={2} axisLine={{ stroke: ct.grid }} tickLine={false} />
                  <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11, fill: ct.tick }} axisLine={false} tickLine={false} />
                  <Tooltip content={({ active, payload, label }) => active && payload?.length ? (
                    <TooltipBox label={label} rows={[{ name: "Spending", value: payload[0].value as number }]} />
                  ) : null} />
                  <Area type="monotone" dataKey="total" stroke="#6366f1" strokeWidth={2} fill="url(#spendingTrendGradient)" dot={false} animationDuration={700} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {trendBarData.length === 0 && rollingBarData.length === 0 && (
            <div className="card text-center py-8 text-gray-400 dark:text-[#525d70] text-sm">
              No transaction data yet. Add transactions to see spending trends.
            </div>
          )}
        </div>
      )}

      {activeTab === "overview" && overview && (
        <>
          {/* Summary strip */}
          <div className="grid grid-cols-3 gap-4">
            <div className="stat-card">
              <span className="stat-label">Total Spent</span>
              <span className="stat-value text-gray-900 dark:text-[#c4ccd8]">{fmt(overview.total_actual)}</span>
            </div>
            <div className="stat-card">
              <span className="stat-label">Budgeted</span>
              <span className="stat-value text-blue-600 dark:text-blue-400">{fmt(overview.total_budgeted)}</span>
            </div>
            <div className="stat-card">
              <span className="stat-label">Variance</span>
              <span className={`stat-value ${parseFloat(overview.total_variance) >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                {parseFloat(overview.total_variance) >= 0 ? "+" : ""}{fmt(overview.total_variance)}
              </span>
            </div>
          </div>

          {/* Total monthly bar chart + average */}
          {barData.length > 1 && (
            <div className="card">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-gray-900 dark:text-[#c4ccd8]">Monthly Spending</h3>
                {avg > 0 && (
                  <span className="text-xs text-gray-500 dark:text-[#6e7888]">
                    avg {fmt(avg)}/mo
                  </span>
                )}
              </div>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={barData} margin={{ top: 16, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
                  <XAxis dataKey="month" tick={{ fontSize: 11, fill: ct.tick }} axisLine={{ stroke: ct.grid }} tickLine={false} />
                  <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11, fill: ct.tick }} axisLine={false} tickLine={false} />
                  <Tooltip content={<TotalBarTooltip />} cursor={{ fill: isDarkMode() ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)" }} />
                  <Bar dataKey="total" fill={ct.barFill} radius={[4, 4, 0, 0]} name="Total" />
                  {avg > 0 && (
                    <ReferenceLine
                      y={avg}
                      stroke={ct.refLine}
                      strokeDasharray="6 3"
                      label={{ value: `avg ${fmt(avg)}`, fill: ct.tick, fontSize: 10, position: "insideTopRight" }}
                    />
                  )}
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Monthly by category stacked chart */}
          {stackedData.length > 0 && allTopCats.length > 0 && (
            <div className="card">
              <div className="flex flex-wrap items-center gap-3 mb-4">
                <h3 className="font-semibold text-gray-900 dark:text-[#c4ccd8]">Spending by Category</h3>
                <div className="flex flex-wrap gap-1.5 ml-auto">
                  {allTopCats.map(cat => {
                    const on = visibleCatIds.has(cat.id);
                    return (
                      <button
                        key={cat.id}
                        onClick={() => toggleCat(cat.id)}
                        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-all ${
                          on
                            ? "border-transparent text-white opacity-90 hover:opacity-100"
                            : "border-gray-200 dark:border-[#2c3040] text-gray-400 dark:text-[#525d70] bg-transparent"
                        }`}
                        style={on ? { background: cat.color } : {}}
                      >
                        <span className="w-2 h-2 rounded-full shrink-0" style={{ background: on ? "rgba(255,255,255,0.6)" : cat.color }} />
                        {cat.name}
                      </button>
                    );
                  })}
                  {catFilter !== null && (
                    <button onClick={() => setCatFilter(null)} className="text-xs text-indigo-500 dark:text-indigo-400 hover:underline px-1">All</button>
                  )}
                </div>
              </div>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={stackedData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
                  <XAxis dataKey="month" tick={{ fontSize: 11, fill: ct.tick }} axisLine={{ stroke: ct.grid }} tickLine={false} />
                  <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11, fill: ct.tick }} axisLine={false} tickLine={false} />
                  <Tooltip content={<StackedTooltip />} cursor={{ fill: isDarkMode() ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)" }} />
                  {allTopCats.filter(c => visibleCatIds.has(c.id)).map(cat => (
                    <Bar key={cat.id} dataKey={cat.name} stackId="a" fill={cat.color} name={cat.name} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Donut chart */}
          {pieData.length > 0 && (
            <div className="card">
              <h3 className="font-semibold text-gray-900 dark:text-[#c4ccd8] mb-4">Period Totals by Category</h3>
              <ResponsiveContainer width="100%" height={260}>
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={65}
                    outerRadius={105}
                    paddingAngle={2}
                    dataKey="value"
                    activeIndex={activeIndex}
                    activeShape={renderActiveShape}
                    onMouseEnter={(_, index) => setActiveIndex(index)}
                    onMouseLeave={() => setActiveIndex(-1)}
                  >
                    {pieData.map((entry: any, i: number) => <Cell key={i} fill={entry.color} />)}
                  </Pie>
                  <Legend formatter={(v) => <span style={{ color: ct.tick }} className="text-sm">{v}</span>} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Category drill-down */}
          <div className="card">
            <h3 className="font-semibold text-gray-900 dark:text-[#c4ccd8] mb-4">Category Breakdown</h3>
            <div className="space-y-3">
              {overview.categories.map((cat: any) => (
                <div key={cat.category_id} className="border border-gray-100 dark:border-[#2c3040] rounded-lg overflow-hidden">
                  <button
                    className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 dark:hover:bg-[#272b38] transition-colors"
                    onClick={() => setExpanded(expanded === cat.category_id ? null : cat.category_id)}
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-3 h-3 rounded-full shrink-0" style={{ background: cat.color }} />
                      <span className="font-medium text-gray-900 dark:text-[#c4ccd8]">{cat.category_name}</span>
                      {cat.children?.length > 0 && (
                        expanded === cat.category_id
                          ? <ChevronDown size={14} className="text-gray-400 dark:text-[#525d70]" />
                          : <ChevronRight size={14} className="text-gray-400 dark:text-[#525d70]" />
                      )}
                    </div>
                    <div className="flex items-center gap-6 text-sm">
                      <span className="text-gray-500 dark:text-[#6e7888]">{fmt(cat.budgeted)} budget</span>
                      <span className={`font-semibold ${parseFloat(cat.variance) < 0 ? "text-red-600 dark:text-[#cc7070]" : "text-gray-700 dark:text-[#9aa3b2]"}`}>
                        {fmt(cat.actual)} spent
                      </span>
                    </div>
                  </button>

                  {parseFloat(cat.budgeted) > 0 && (
                    <div className="px-4 pb-2">
                      <ProgressBar actual={parseFloat(cat.actual)} budgeted={parseFloat(cat.budgeted)} />
                    </div>
                  )}

                  {expanded === cat.category_id && cat.children?.length > 0 && (
                    <div className="border-t border-gray-100 dark:border-[#2c3040] divide-y divide-gray-50 dark:divide-[#2c3040]">
                      {cat.children
                        .filter((ch: any) => parseFloat(ch.actual) > 0 || parseFloat(ch.budgeted) > 0)
                        .map((ch: any) => (
                          <div key={ch.category_id} className="px-6 py-2.5 bg-gray-50/50 dark:bg-[#1a1e2a]">
                            <div className="flex items-center justify-between mb-1">
                              <div className="flex items-center gap-2">
                                <div className="w-2 h-2 rounded-full" style={{ background: ch.color }} />
                                <span className="text-sm text-gray-700 dark:text-[#9aa3b2]">{ch.category_name}</span>
                              </div>
                              <div className="flex items-center gap-4 text-xs text-gray-500 dark:text-[#6e7888]">
                                {Object.entries(ch.breakdown_by_source).map(([src, amt]: any) => (
                                  <span key={src}>{src}: <strong className="text-gray-700 dark:text-[#9aa3b2]">{fmt(amt)}</strong></span>
                                ))}
                                <span className="font-semibold text-gray-900 dark:text-[#c4ccd8]">{fmt(ch.actual)}</span>
                              </div>
                            </div>
                            {parseFloat(ch.budgeted) > 0 && <ProgressBar actual={parseFloat(ch.actual)} budgeted={parseFloat(ch.budgeted)} />}
                          </div>
                        ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {activeTab === "overview" && isLoading && <div className="text-center py-8 text-gray-400 dark:text-[#525d70] text-sm">Loading spending data…</div>}
      {activeTab === "overview" && !isLoading && !overview && <div className="card text-center py-8 text-gray-400 dark:text-[#525d70]">Select a date range to view spending.</div>}

      {activeTab === "flow" && (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <select className="input w-auto" value={sankeyYear} onChange={e => setSankeyYear(parseInt(e.target.value))}>
              {[-1, 0, 1].map(d => { const y = new Date().getFullYear() + d; return <option key={y} value={y}>{y}</option>; })}
            </select>
            <select className="input w-auto" value={sankeyMonth} onChange={e => setSankeyMonth(parseInt(e.target.value))}>
              {MONTH_NAMES.map((m, i) => <option key={i + 1} value={i + 1}>{m}</option>)}
            </select>
          </div>
          <SankeyChart data={sankeyData} />
        </div>
      )}
      {activeTab === "tax" && (
        <div className="card max-w-md space-y-4">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">Tax Summary Export</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400">Download a CSV of all transactions in tax-deductible categories for the selected year. Mark categories as tax deductible in Settings → Categories.</p>
          <div className="flex items-center gap-3">
            <div>
              <label className="label">Year</label>
              <select className="input w-auto" value={taxYear} onChange={e => setTaxYear(parseInt(e.target.value))}>
                {[-1, 0, 1].map(d => { const y = new Date().getFullYear() + d; return <option key={y} value={y}>{y}</option>; })}
              </select>
            </div>
            <div className="pt-5">
              <button
                className="btn-primary text-sm"
                onClick={async () => {
                  const res = await api.get(`/spending/tax-summary?year=${taxYear}&format=csv`, { responseType: "blob" });
                  const url = URL.createObjectURL(res.data);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `tax-summary-${taxYear}.csv`;
                  a.click();
                  URL.revokeObjectURL(url);
                }}
              >
                Download CSV
              </button>
            </div>
          </div>
        </div>
      )}
      {showHelp && <HelpPanel title="Spending Analysis" body={"Analyze your spending by category across any date range.\n\nOverview tab: budgeted vs. actual by category with breakdown by account and card.\nTrends tab: year-over-year comparison and 24-month rolling totals.\nFlow tab: Sankey diagram showing income sources flowing into expense categories.\nTax Export tab: download a CSV of deductible transactions for tax filing."} onClose={() => setShowHelp(false)} />}
    </div>
  );
}

function SankeyChart({ data }: { data: any }) {
  const WIDTH = 720;
  const HEIGHT = 400;
  const PADDING = 120;

  if (!data || (!data.nodes?.length)) {
    return <div className="card text-center py-12 text-gray-400 text-sm">No income or expense data for this period.</div>;
  }

  const nodeList = data.nodes.map((n: any) => ({ ...n }));

  const links = data.links.map((l: any) => ({
    source: l.source,
    target: l.target,
    value: parseFloat(l.value),
  })).filter((l: any) => l.source && l.target && l.value > 0);

  if (!links.length) {
    return <div className="card text-center py-12 text-gray-400 text-sm">No flow data for this period.</div>;
  }

  const sankeyLayout = d3Sankey<{ id: string; name: string; type: string }, { value: number }>()
    .nodeId((d: any) => d.id)
    .nodeAlign(sankeyLeft)
    .nodeWidth(14)
    .nodePadding(16)
    .extent([[PADDING, 10], [WIDTH - PADDING, HEIGHT - 10]]);

  let graph: any;
  try {
    graph = sankeyLayout({ nodes: nodeList.map((n: any) => ({ ...n })), links: links.map((l: any) => ({ ...l })) });
  } catch {
    return <div className="card text-center py-12 text-gray-400 text-sm">Could not render flow diagram for this data.</div>;
  }

  const fmt2 = (v: number) => v >= 1000 ? `$${(v / 1000).toFixed(1)}k` : `$${v.toFixed(0)}`;

  return (
    <div className="card overflow-x-auto">
      <h3 className="font-semibold text-gray-900 mb-4">Income → Expense Flow</h3>
      <svg width="100%" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="min-w-[520px]">
        {graph.links.map((l: any, i: number) => (
          <path
            key={i}
            d={sankeyLinkHorizontal()(l) ?? ""}
            fill="none"
            stroke="#6366f1"
            strokeOpacity={0.25}
            strokeWidth={Math.max(1, l.width)}
          />
        ))}
        {graph.nodes.map((n: any, i: number) => {
          const isLeft = n.x0 < WIDTH / 2;
          const color = n.type === "income" ? "#10b981" : n.type === "income_total" ? "#6366f1" : "#f59e0b";
          const labelX = isLeft ? n.x0 - 6 : n.x1 + 6;
          const anchor = isLeft ? "end" : "start";
          const midY = (n.y0 + n.y1) / 2;
          return (
            <g key={i}>
              <rect x={n.x0} y={n.y0} width={n.x1 - n.x0} height={n.y1 - n.y0} fill={color} rx={2} />
              <text x={labelX} y={midY - 5} textAnchor={anchor} fontSize={11} fill={isDarkMode() ? "#c4ccd8" : "#374151"} fontWeight={500}>
                {n.name}
              </text>
              <text x={labelX} y={midY + 8} textAnchor={anchor} fontSize={10} fill="#6b7280">
                {fmt2(n.value)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

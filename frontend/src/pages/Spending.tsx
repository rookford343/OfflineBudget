import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { spendingApi, accountsApi, cardsApi, analyticsApi, merchantsApi } from "../api";
import { sankey as d3Sankey, sankeyLinkHorizontal, sankeyLeft } from "d3-sankey";
import { fmt, firstOfMonth, today, quickRange } from "../lib/utils";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, ReferenceLine,
  Sector,
} from "recharts";
import { ChevronDown, ChevronRight, HelpCircle, Pencil, X } from "lucide-react";
import HelpPanel from "../components/HelpPanel";
import { sortCategoryList, byName } from "../lib/selectOptions";

function isDarkMode(): boolean {
  return document.documentElement.classList.contains("dark");
}

function chartTheme() {
  const dark = isDarkMode();
  return {
    grid:    dark ? "#3a4051" : "#e5e7eb",
    tick:    dark ? "#8f99a8" : "#6b7280",
    refLine: dark ? "#4a5568" : "#9ca3af",
    tooltip: dark ? "#2a2f3d" : "#ffffff",
    tooltipBorder: dark ? "#3a4051" : "#e5e7eb",
    tooltipText: dark ? "#c4ccd8" : "#111827",
    tooltipMuted: dark ? "#8f99a8" : "#6b7280",
    barFill: dark ? "#a5b4fc" : "#6366f1",
  };
}

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export default function Spending() {
  const [showHelp, setShowHelp] = useState(false);
  const [activeTab, setActiveTab] = useState<"overview" | "trends" | "merchants" | "flow">("overview");
  const [renameTarget, setRenameTarget] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const qc = useQueryClient();
  const renameMut = useMutation({
    mutationFn: (v: { pattern: string; display_name: string }) => merchantsApi.createAlias(v),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["spending-merchants"] });
      setRenameTarget(null);
    },
  });
  const [sankeyYear, setSankeyYear] = useState(new Date().getFullYear());
  const [sankeyMonth, setSankeyMonth] = useState(new Date().getMonth() + 1);
  const [start, setStart] = useState(firstOfMonth());
  const [end, setEnd] = useState(today());
  const [sourceKey, setSourceKey] = useState<string>("all");
  const [catFilter, setCatFilter] = useState<Set<number> | null>(null);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [merchantSortCol, setMerchantSortCol] = useState<"name" | "count" | "total">("total");
  const [merchantSortDir, setMerchantSortDir] = useState<"asc" | "desc">("desc");
  const [trendsRangeMonths, setTrendsRangeMonths] = useState(12);

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

  const { data: rollingMonthly = [] } = useQuery({
    queryKey: ["rolling-monthly", trendsRangeMonths],
    queryFn: () => analyticsApi.rollingMonthly(trendsRangeMonths),
    enabled: activeTab === "trends",
  });

  const { data: sankeyData } = useQuery({
    queryKey: ["sankey", sankeyYear, sankeyMonth],
    queryFn: () => spendingApi.sankey(sankeyYear, sankeyMonth),
    enabled: activeTab === "flow",
  });

  const { data: merchantData = [], isLoading: merchantLoading } = useQuery({
    queryKey: ["spending-merchants", start, end, selectedAccountId, selectedCardId],
    queryFn: () => spendingApi.byMerchant(start, end, selectedAccountId, selectedCardId),
    enabled: activeTab === "merchants" && !!start && !!end,
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

  // Recharts data for total monthly bars, split checking/cards for the
  // stacked chart -- both fields already come back from /spending/monthly.
  const barData = monthly.map((m: any) => ({
    month: m.month,
    total: parseFloat(m.total),
    checking: parseFloat(m.checking),
    cards: parseFloat(m.cards),
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

  // The overview arrives as a Necessities/Wants/Charity tree, but those
  // buckets aren't what you budget against -- flatten to the budget
  // categories themselves and rank by spend. A parent that carries spending
  // directly (no children) stays in the list under its own name.
  const budgetCategories = useMemo(() => {
    const out: any[] = [];
    (overview?.categories ?? []).forEach((parent: any) => {
      const kids = parent.children ?? [];
      if (kids.length === 0) {
        if (parseFloat(parent.actual) > 0 || parseFloat(parent.budgeted) > 0) {
          out.push({ ...parent, group: null });
        }
        return;
      }
      kids.forEach((ch: any) => {
        if (parseFloat(ch.actual) > 0 || parseFloat(ch.budgeted) > 0) {
          out.push({ ...ch, group: parent.category_name });
        }
      });
      // Spending filed on the parent itself rather than one of its children
      // would silently vanish if only children were listed.
      const kidSum = kids.reduce((s: number, ch: any) => s + parseFloat(ch.actual), 0);
      const direct = parseFloat(parent.actual) - kidSum;
      if (direct > 0.005) {
        out.push({
          category_id: -parent.category_id, category_name: `${parent.category_name} (uncategorized)`,
          color: parent.color, actual: String(direct), budgeted: "0",
          breakdown_by_source: {}, group: parent.category_name, children: [],
        });
      }
    });
    return out.sort((a, b) => parseFloat(b.actual) - parseFloat(a.actual));
  }, [overview]);

  // Overview's Top Merchants panel. Its own query so it follows the page's
  // date range and source filter, and stays loaded on the Overview tab rather
  // than only when the Merchants tab is open.
  const { data: overviewMerchantsRaw = [] } = useQuery<any[]>({
    queryKey: ["spending-merchants-overview", start, end, selectedAccountId, selectedCardId],
    queryFn: () => spendingApi.byMerchant(start, end, selectedAccountId ?? undefined, selectedCardId ?? undefined, 8),
    enabled: activeTab === "overview" && !!start && !!end,
  });
  const overviewMerchants = overviewMerchantsRaw.slice(0, 8);

  // Month drill-down: click a bar to see what actually drove that month.
  const [drillMonth, setDrillMonth] = useState<string | null>(null);
  const drillRange = drillMonth
    ? (() => {
        const [y, m] = drillMonth.split("-").map(Number);
        const last = new Date(y, m, 0).getDate();
        return { start: `${drillMonth}-01`, end: `${drillMonth}-${String(last).padStart(2, "0")}` };
      })()
    : null;

  const { data: drillMerchants = [] } = useQuery<any[]>({
    queryKey: ["drill-merchants", drillMonth, selectedAccountId, selectedCardId],
    queryFn: () => spendingApi.byMerchant(drillRange!.start, drillRange!.end,
      selectedAccountId ?? undefined, selectedCardId ?? undefined, 10),
    enabled: !!drillRange,
  });
  // Goes through /spending/transactions, not the raw transaction list: these
  // rows have to add up to the bar that was clicked, so they must share the
  // bar's filters rather than merely resemble them.
  const { data: drillTxns = [] } = useQuery<any[]>({
    queryKey: ["drill-txns", drillMonth, selectedAccountId, selectedCardId],
    queryFn: () => spendingApi.lineItems(drillRange!.start, drillRange!.end,
      selectedAccountId ?? undefined, selectedCardId ?? undefined, 12),
    enabled: !!drillRange,
  });

  // Pie chart data
  const pieData = (overview?.categories ?? [])
    .filter((c: any) => parseFloat(c.actual) > 0)
    .map((c: any) => ({ name: c.category_name, value: parseFloat(c.actual), color: c.color }));

  const ct = chartTheme();
  // Category colours are user-set and some are pale, so white-on-swatch is a
  // coin flip -- "Other" (#9ca3af) measured 2.54:1 and amber 3.19:1.
  //
  // Compare both candidates and take the better contrast rather than guessing
  // from a luminance cutoff: a fixed threshold still picked white for both of
  // those, because mid-tones are the exact case a single cutoff gets wrong.
  const readableOn = (hex: string): string => {
    const h = (hex || "#888888").replace("#", "");
    if (h.length !== 6) return "#ffffff";
    const lum = (c: string) => {
      const [r, g, b] = [0, 2, 4].map(i => parseInt(c.slice(i, i + 2), 16) / 255);
      const f = (v: number) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
      return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
    };
    const ratio = (a: number, b: number) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    const L = lum(h);
    return ratio(L, lum("1a1d26")) >= ratio(L, lum("ffffff")) ? "#1a1d26" : "#ffffff";
  };

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

  const StackedTooltip = ({ active, payload, label }: any) =>
    active && payload?.length ? (
      <TooltipBox
        label={label}
        rows={payload
          .filter((p: any) => Number(p.value) > 0)
          .map((p: any) => ({ name: p.name, value: p.value, color: p.fill }))}
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
        <text x={cx} y={cy + 24} textAnchor="middle" fill={isDarkMode() ? "#8f99a8" : "#6b7280"} fontSize={11}>{pctStr}</text>
      </g>
    );
  }

  // "$1,240 Checking · $310 Chase Freedom" -- omits a source entirely if
  // it's $0, so a category/bucket that's 100% one source doesn't show a
  // pointless "$0 Cards". Returns null when there's nothing worth showing
  // (zero or one non-zero source), so callers can skip rendering the line
  // at all. Caps at the top two sources by amount, folding the rest into a
  // "+N more" suffix so the line still fits a one-third-width stat card
  // when `breakdown_by_source` keys are real card names rather than just
  // "Checking"/"Cards".
  //
  // `headline` is the total this split is supposed to add up to. A
  // top-level category can carry spend directly on itself (no child --
  // see the "(uncategorized)" synthetic row above), and that spend IS
  // counted in headline numbers like `disc`/`fixed`/`total_actual` but
  // ISN'T captured by a source-split bucket built by walking only
  // `children[].breakdown_by_source`. Rather than render a split that
  // silently doesn't sum to the number above it, refuse to render at all
  // when the two disagree by more than a cent. Omit `headline` when the
  // bucket IS the full total already (e.g. a leaf category's own
  // breakdown_by_source), since there's no gap to reconcile.
  function sourceSplitLabel(breakdown: Record<string, number>, headline?: number): string | null {
    const nonZero = Object.entries(breakdown).filter(([, v]) => v > 0.005);
    if (nonZero.length < 2) return null;
    if (headline !== undefined) {
      const sum = nonZero.reduce((s, [, v]) => s + v, 0);
      if (Math.abs(sum - headline) > 0.01) return null;
    }
    const sorted = nonZero.sort((a, b) => b[1] - a[1]);
    const shown = sorted.slice(0, 2);
    const extra = sorted.length - shown.length;
    const label = shown
      .map(([name, v]) => `${fmt(v, { minimumFractionDigits: 0, maximumFractionDigits: 0 })} ${name}`)
      .join(" · ");
    return extra > 0 ? `${label} +${extra} more` : label;
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

  const rollingBarData = useMemo(() => {
    return (rollingMonthly as any[]).map((r: any) => ({
      month: r.month,
      total: parseFloat(r.total),
      checking: parseFloat(r.checking),
      cards: parseFloat(r.cards),
    }));
  }, [rollingMonthly]);

  return (
    <div className="space-y-6">
      {/* Header + controls */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-[#c4ccd8] flex items-center gap-1.5">Spending <button onClick={() => setShowHelp(true)} className="text-gray-400 hover:text-indigo-500 font-normal"><HelpCircle size={15} /></button></h2>
          <p className="text-sm text-gray-500 dark:text-[#8f99a8]">Across checking + all credit cards</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <select className="input w-auto" value={sourceKey} onChange={e => { setSourceKey(e.target.value); setCatFilter(null); }}>
            <option value="all">All Sources</option>
            {byName(checkingAccounts).map((a: any) => <option key={`account-${a.id}`} value={`account-${a.id}`}>{a.name}</option>)}
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
        {(["overview", "trends", "merchants", "flow"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium capitalize border-b-2 transition-colors ${
              activeTab === tab
                ? "border-indigo-500 text-indigo-600 dark:text-indigo-300"
                : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300"
            }`}
          >
            {tab === "flow" ? "Flow" : tab}
          </button>
        ))}
      </div>

      {/* Trends tab */}
      {activeTab === "trends" && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-gray-900 dark:text-[#c4ccd8]">Spending Over Time</h3>
            <div className="flex gap-1">
              {([["6M", 6], ["YTD", new Date().getMonth() + 1], ["1Y", 12], ["2Y", 24]] as const).map(([label, months]) => (
                <button
                  key={label}
                  type="button"
                  className={`px-2.5 py-1 text-xs rounded-md ${
                    trendsRangeMonths === months
                      ? "bg-indigo-500 text-white"
                      : "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 hover:text-indigo-600 dark:hover:text-indigo-400"
                  }`}
                  onClick={() => setTrendsRangeMonths(months)}
                >{label}</button>
              ))}
            </div>
          </div>

          {rollingBarData.length > 0 ? (
            <div className="card">
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={rollingBarData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
                  <XAxis dataKey="month" tick={{ fontSize: 10, fill: ct.tick }} interval={trendsRangeMonths > 12 ? 2 : 0} axisLine={{ stroke: ct.grid }} tickLine={false} />
                  <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11, fill: ct.tick }} axisLine={false} tickLine={false} />
                  <Tooltip content={<StackedTooltip />} cursor={{ fill: isDarkMode() ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)" }} />
                  <Legend formatter={(v) => <span style={{ color: ct.tick }} className="text-sm">{v}</span>} />
                  <Bar dataKey="checking" stackId="spend" fill={ct.barFill} name="Checking" />
                  <Bar dataKey="cards" stackId="spend" fill="#f59e0b" radius={[3, 3, 0, 0]} name="Cards" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="card text-center py-8 text-gray-400 dark:text-[#949daf] text-sm">
              No transaction data yet. Add transactions to see spending trends.
            </div>
          )}
        </div>
      )}

      {activeTab === "overview" && overview && (
        <>
          {/* Discretionary first: the part of spending that was actually a
              decision this month. Fixed commitments (mortgage, tithe,
              insurance) dominate the raw total and drown it out -- in July
              they were $9,722 of $15,772, so "Total Spent" alone told Dan
              nothing he could act on. */}
          {(() => {
            const disc = parseFloat(overview.discretionary_actual ?? "0");
            const discBudget = parseFloat(overview.discretionary_budgeted ?? "0");
            const fixed = parseFloat(overview.fixed_actual ?? "0");
            const left = discBudget - disc;
            const pct = discBudget > 0 ? (disc / discBudget) * 100 : 0;
            const over = left < 0;

            // breakdown_by_source lives on each child category; bucket by
            // the PARENT's is_discretionary flag to get discretionary vs.
            // fixed vs. total split by source, with no new backend call.
            const discBySource: Record<string, number> = {};
            const fixedBySource: Record<string, number> = {};
            (overview.categories ?? []).forEach((top: any) => {
              const bucket = top.is_discretionary ? discBySource : fixedBySource;
              (top.children ?? []).forEach((ch: any) => {
                Object.entries(ch.breakdown_by_source ?? {}).forEach(([label, amt]) => {
                  bucket[label] = (bucket[label] ?? 0) + parseFloat(amt as string);
                });
              });
            });
            const totalBySource: Record<string, number> = {};
            [discBySource, fixedBySource].forEach(bucket => {
              Object.entries(bucket).forEach(([label, amt]) => {
                totalBySource[label] = (totalBySource[label] ?? 0) + amt;
              });
            });

            return (
              <div className="space-y-4">
                {discBudget > 0 && (
                  <div className={`card ${over
                    ? "bg-gradient-to-br from-red-50 to-orange-50 border-red-100 dark:from-red-950/40 dark:to-orange-950/30 dark:border-red-900/50"
                    : "bg-gradient-to-br from-emerald-50 to-teal-50 border-emerald-100 dark:from-emerald-950/40 dark:to-teal-950/30 dark:border-emerald-900/50"}`}>
                    <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">Discretionary spending</p>
                    <p className={`text-3xl font-bold tabular-nums ${over ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"}`}>
                      {over ? `${fmt(Math.abs(left))} over` : `${fmt(left)} left`}
                    </p>
                    <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                      {fmt(disc)} spent of {fmt(discBudget)} budgeted
                    </p>
                    <div className="mt-3 h-2.5 bg-white/70 dark:bg-black/30 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full ${pct >= 100 ? "bg-red-500" : pct >= 80 ? "bg-amber-500" : "bg-emerald-500"}`}
                        style={{ width: `${Math.min(100, pct)}%` }} />
                    </div>
                  </div>
                )}
                <div className="grid grid-cols-3 gap-4">
                  <div className="stat-card">
                    <span className="stat-label">Discretionary</span>
                    <span className="stat-value text-gray-900 dark:text-[#c4ccd8]">{fmt(disc)}</span>
                    <span className="text-xs text-gray-400">what you chose</span>
                    {sourceSplitLabel(discBySource, disc) && (
                      <span className="text-xs text-gray-400 dark:text-[#8f99a8] mt-0.5">{sourceSplitLabel(discBySource, disc)}</span>
                    )}
                  </div>
                  <div className="stat-card">
                    <span className="stat-label">Fixed Commitments</span>
                    <span className="stat-value text-gray-500 dark:text-gray-400">{fmt(fixed)}</span>
                    <span className="text-xs text-gray-400">mortgage, tithe, insurance</span>
                    {sourceSplitLabel(fixedBySource, fixed) && (
                      <span className="text-xs text-gray-400 dark:text-[#8f99a8] mt-0.5">{sourceSplitLabel(fixedBySource, fixed)}</span>
                    )}
                  </div>
                  <div className="stat-card">
                    <span className="stat-label">Total Spent</span>
                    <span className="stat-value text-gray-900 dark:text-[#c4ccd8]">{fmt(overview.total_actual)}</span>
                    <span className="text-xs text-gray-400">of {fmt(overview.total_budgeted)} budgeted</span>
                    {sourceSplitLabel(totalBySource, parseFloat(overview.total_actual)) && (
                      <span className="text-xs text-gray-400 dark:text-[#8f99a8] mt-0.5">{sourceSplitLabel(totalBySource, parseFloat(overview.total_actual))}</span>
                    )}
                  </div>
                </div>
              </div>
            );
          })()}

          {/* Total monthly bar chart + average */}
          {barData.length > 1 && (
            <div className="card">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-gray-900 dark:text-[#c4ccd8]">Monthly Spending</h3>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-gray-400">click a bar for detail</span>
                  {avg > 0 && (
                    <span className="text-xs text-gray-500 dark:text-[#8f99a8]">
                      avg {fmt(avg)}/mo
                    </span>
                  )}
                </div>
              </div>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={barData} margin={{ top: 16, right: 12, left: 0, bottom: 0 }}
                  onClick={(state: any) => {
                    const month = state?.activeLabel;
                    if (month) setDrillMonth(m => (m === month ? null : month));
                  }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
                  <XAxis dataKey="month" tick={{ fontSize: 11, fill: ct.tick }} axisLine={{ stroke: ct.grid }} tickLine={false} />
                  <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11, fill: ct.tick }} axisLine={false} tickLine={false} />
                  <Tooltip content={<StackedTooltip />} cursor={{ fill: isDarkMode() ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)" }} />
                  <Bar dataKey="checking" stackId="spend" fill={ct.barFill} name="Checking" className="cursor-pointer" />
                  <Bar dataKey="cards" stackId="spend" fill="#f59e0b" radius={[4, 4, 0, 0]} name="Cards" className="cursor-pointer" />
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

          {/* Month drill-down. Answers "why was that month high?" in place,
              instead of making you re-derive it from the Transactions page. */}
          {drillMonth && (
            <div className="card border-indigo-200 dark:border-indigo-900/60">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h3 className="font-semibold text-gray-900 dark:text-[#c4ccd8]">
                    {new Date(drillMonth + "-01T12:00:00").toLocaleDateString("en-US", { month: "long", year: "numeric" })}
                  </h3>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    Top {drillTxns.length} by amount · checking + card, excluding transfers and card payoffs
                  </p>
                </div>
                <button onClick={() => setDrillMonth(null)} className="btn-ghost p-1 text-gray-400 hover:text-gray-600">
                  <X size={16} />
                </button>
              </div>

              <div className="grid md:grid-cols-2 gap-5">
                <div>
                  <h4 className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">Top Merchants</h4>
                  {drillMerchants.length === 0 && <p className="text-sm text-gray-400">No merchant activity.</p>}
                  <div className="space-y-1.5">
                    {drillMerchants.map((m: any) => (
                      <div key={m.name} className="flex items-baseline justify-between gap-3 text-sm">
                        <span className="truncate text-gray-700 dark:text-gray-300">{m.name}</span>
                        <span className="shrink-0 tabular-nums font-medium">
                          {fmt(m.total)}<span className="ml-1.5 text-xs font-normal text-gray-400">{m.count}x</span>
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <h4 className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">Largest Transactions</h4>
                  <div className="space-y-1.5 max-h-64 overflow-y-auto">
                    {drillTxns.map((x: any, i: number) => (
                        <div key={i} className="flex items-baseline justify-between gap-3 text-sm">
                          <span className="truncate text-gray-700 dark:text-gray-300" title={x.description}>
                            <span className="text-gray-400 mr-1.5 text-xs tabular-nums">
                              {new Date(x.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                            </span>
                            {x.description}
                            {x.source === "card" && (
                              <span className="ml-1.5 text-[10px] uppercase tracking-wide text-gray-400">card</span>
                            )}
                          </span>
                          <span className="shrink-0 tabular-nums font-medium text-red-600 dark:text-red-400">
                            {fmt(x.amount)}
                          </span>
                        </div>
                      ))}
                  </div>
                </div>
              </div>
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
                            ? "border-transparent opacity-95 hover:opacity-100"
                            : "border-gray-200 dark:border-[#3a4051] text-gray-400 dark:text-[#949daf] bg-transparent"
                        }`}
                        style={on ? { background: cat.color, color: readableOn(cat.color) } : {}}
                      >
                        <span className="w-2 h-2 rounded-full shrink-0" style={{ background: on ? "currentColor" : cat.color, opacity: on ? 0.55 : 1 }} />
                        {cat.name}
                      </button>
                    );
                  })}
                  {catFilter !== null && (
                    <button onClick={() => setCatFilter(null)} className="text-xs text-indigo-500 dark:text-indigo-300 hover:underline px-1">All</button>
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

          {/* Top merchants. Replaced the donut 2026-08-15: it plotted the same
              category totals the stacked bar chart directly above already
              showed, just in a shape that's worse at comparison. Merchants are
              the one cut of this data not available anywhere else on the
              Overview, and the actionable one -- categories tell you Groceries
              is high, merchants tell you where it went. */}
          {overviewMerchants.length > 0 && (
            <div className="card">
              <div className="flex items-baseline justify-between mb-3">
                <h3 className="font-semibold text-gray-900 dark:text-[#c4ccd8]">Top Merchants</h3>
                <button onClick={() => setActiveTab("merchants")}
                  className="text-xs text-indigo-600 dark:text-indigo-300 hover:underline">
                  See all →
                </button>
              </div>
              <div className="space-y-2">
                {overviewMerchants.map((m: any) => {
                  const top = Number(overviewMerchants[0].total) || 1;
                  const pct = (Number(m.total) / top) * 100;
                  return (
                    <div key={m.name}>
                      <div className="flex items-baseline justify-between gap-3 text-sm">
                        <span className="truncate text-gray-700 dark:text-gray-300">{m.name}</span>
                        <span className="shrink-0 tabular-nums font-medium text-gray-900 dark:text-gray-100">
                          {fmt(m.total)}
                          <span className="ml-1.5 text-xs font-normal text-gray-400">{m.count}x</span>
                        </span>
                      </div>
                      <div className="mt-1 h-1.5 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                        <div className="h-full rounded-full bg-indigo-400" style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Spending by budget category. Ranked by spend rather than nested
              under Necessities/Wants/Charity -- the question is which
              category ran hot, and the bucket it belongs to is a label, not
              the grouping. */}
          <div className="card">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold text-gray-900 dark:text-[#c4ccd8]">Spending by Category</h3>
              <span className="text-xs text-gray-400 dark:text-[#8f99a8]">{budgetCategories.length} categories</span>
            </div>
            {budgetCategories.length === 0 && (
              <p className="text-sm text-gray-400 dark:text-[#949daf]">No categorized spending in this range.</p>
            )}
            <div className="space-y-3">
              {budgetCategories.map((cat: any) => {
                const actual = parseFloat(cat.actual);
                const budgeted = parseFloat(cat.budgeted);
                const over = budgeted > 0 && actual > budgeted;
                const split = sourceSplitLabel(
                  Object.fromEntries(
                    Object.entries(cat.breakdown_by_source ?? {}).map(([k, v]) => [k, parseFloat(v as string)])
                  )
                );
                return (
                  <div key={cat.category_id}>
                    <div className="flex items-baseline justify-between gap-3 mb-1">
                      <div className="flex items-center gap-2 min-w-0">
                        <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: cat.color }} />
                        <span className="text-sm font-medium text-gray-900 dark:text-[#c4ccd8] truncate">
                          {cat.category_name}
                        </span>
                        {cat.group && (
                          <span className="text-[10px] uppercase tracking-wide text-gray-400 dark:text-[#949daf] shrink-0">
                            {cat.group}
                          </span>
                        )}
                      </div>
                      <div className="flex items-baseline gap-2 shrink-0 text-sm">
                        <span className={`font-semibold tabular-nums ${over ? "text-red-600 dark:text-[#eda2a2]" : "text-gray-900 dark:text-[#c4ccd8]"}`}>
                          {fmt(actual)}
                        </span>
                        <span className="text-xs text-gray-400 dark:text-[#8f99a8] tabular-nums">
                          {budgeted > 0 ? `of ${fmt(budgeted)}` : "unbudgeted"}
                        </span>
                      </div>
                    </div>
                    {split && <p className="text-xs text-gray-400 dark:text-[#8f99a8] mb-1">{split}</p>}
                    {budgeted > 0 && <ProgressBar actual={actual} budgeted={budgeted} />}
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}

      {activeTab === "overview" && isLoading && <div className="text-center py-8 text-gray-400 dark:text-[#949daf] text-sm">Loading spending data…</div>}
      {activeTab === "overview" && !isLoading && !overview && <div className="card text-center py-8 text-gray-400 dark:text-[#949daf]">Select a date range to view spending.</div>}

      {activeTab === "merchants" && (
        <div className="space-y-4">
          {merchantLoading && <div className="text-center py-8 text-gray-400 text-sm">Loading…</div>}
          {!merchantLoading && merchantData.length === 0 && (
            <div className="card text-center py-8 text-gray-400">No spending data for this range.</div>
          )}
          {!merchantLoading && merchantData.length > 0 && (() => {
            function toggleMerchantSort(col: "name" | "count" | "total") {
              if (merchantSortCol === col) setMerchantSortDir(d => d === "asc" ? "desc" : "asc");
              else { setMerchantSortCol(col); setMerchantSortDir(col === "name" ? "asc" : "desc"); }
            }
            const sorted = [...(merchantData as any[])].sort((a, b) => {
              let cmp = 0;
              if (merchantSortCol === "name") cmp = a.name.localeCompare(b.name);
              else if (merchantSortCol === "count") cmp = Number(a.count) - Number(b.count);
              else cmp = Number(a.total) - Number(b.total);
              return merchantSortDir === "asc" ? cmp : -cmp;
            });
            const maxTotal = Math.max(...sorted.map((m: any) => Number(m.total)));
            function SortArrow({ col }: { col: "name" | "count" | "total" }) {
              if (merchantSortCol !== col) return <span className="ml-1 text-gray-300 dark:text-gray-400">↕</span>;
              return <span className="ml-1">{merchantSortDir === "asc" ? "↑" : "↓"}</span>;
            }
            return (
              <div className="card p-0 overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 dark:bg-gray-800/50">
                    <tr>
                      <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase w-8">#</th>
                      <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase cursor-pointer select-none hover:text-gray-700 dark:hover:text-gray-300" onClick={() => toggleMerchantSort("name")}>
                        Merchant / Description <SortArrow col="name" />
                      </th>
                      <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase hidden sm:table-cell cursor-pointer select-none hover:text-gray-700 dark:hover:text-gray-300" onClick={() => toggleMerchantSort("count")}>
                        Transactions <SortArrow col="count" />
                      </th>
                      <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase cursor-pointer select-none hover:text-gray-700 dark:hover:text-gray-300" onClick={() => toggleMerchantSort("total")}>
                        Total <SortArrow col="total" />
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                    {sorted.map((m: any, i: number) => {
                      const pct = maxTotal > 0 ? (Number(m.total) / maxTotal) * 100 : 0;
                      return (
                        <tr key={m.name} className="hover:bg-gray-50 dark:hover:bg-gray-800/30 relative">
                          <td className="px-4 py-2 text-gray-400 tabular-nums">{i + 1}</td>
                          <td className="px-4 py-2 text-gray-900 dark:text-gray-100 max-w-xs group">
                            <div className="relative">
                              <div className="absolute inset-0 bg-indigo-50 dark:bg-indigo-900/20 rounded" style={{ width: `${pct}%` }} />
                              <span className="relative inline-flex items-center gap-1.5">
                                {m.name}
                                {/* Names are auto-grouped from raw bank descriptors, and the
                                    heuristics will get some wrong. Renaming here is what keeps a
                                    bad grouping visible and fixable instead of quietly wrong. */}
                                <button
                                  onClick={() => { setRenameTarget(m.name); setRenameValue(m.name); }}
                                  className="opacity-0 group-hover:opacity-100 text-gray-300 hover:text-indigo-500 transition-opacity"
                                  title="Rename or merge this merchant"
                                >
                                  <Pencil size={11} />
                                </button>
                              </span>
                            </div>
                          </td>
                          <td className="px-4 py-2 text-right text-gray-400 tabular-nums hidden sm:table-cell">{m.count}×</td>
                          <td className="px-4 py-2 text-right font-semibold tabular-nums text-red-600 dark:text-red-400">{fmt(m.total)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            );
          })()}
        </div>
      )}

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
      {showHelp && <HelpPanel title="Spending Analysis" body={"Analyze your spending by category across any date range.\n\nOverview tab: budgeted vs. actual by category, split by checking vs. card.\nTrends tab: spending over a range you choose, split by checking vs. card.\nFlow tab: Sankey diagram showing income sources flowing into expense categories."} onClose={() => setShowHelp(false)} />}
      {renameTarget && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
             onClick={() => setRenameTarget(null)}>
          <div className="card w-full max-w-sm space-y-3" onClick={e => e.stopPropagation()}>
            <h3 className="font-semibold text-gray-900 dark:text-gray-100">Rename merchant</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Merchant names are grouped automatically from raw bank descriptors. Rename
              <span className="font-medium"> {renameTarget}</span> — or type an existing merchant's
              name to merge the two together.
            </p>
            <input className="input w-full" value={renameValue} autoFocus
              onChange={e => setRenameValue(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && renameValue.trim()) renameMut.mutate({ pattern: renameTarget, display_name: renameValue.trim() }); }} />
            <div className="flex justify-end gap-2">
              <button className="btn-secondary text-sm" onClick={() => setRenameTarget(null)}>Cancel</button>
              <button className="btn-primary text-sm"
                disabled={!renameValue.trim() || renameMut.isPending}
                onClick={() => renameMut.mutate({ pattern: renameTarget, display_name: renameValue.trim() })}>
                {renameMut.isPending ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


function SankeyChart({ data }: { data: any }) {
  const WIDTH = 720;
  const HEIGHT = 400;
  const PADDING = 140;

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
    .nodePadding(20)
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
          // Semantic green/red for income/expense, indigo for the total
          // pool node -- was a three-color scheme (green/indigo/amber) that
          // didn't map expense to the red used everywhere else on this page.
          const color = n.type === "income" ? "#10b981" : n.type === "income_total" ? "#6366f1" : "#dc2626";
          const labelX = isLeft ? n.x0 - 6 : n.x1 + 6;
          const anchor = isLeft ? "end" : "start";
          const midY = (n.y0 + n.y1) / 2;
          return (
            <g key={i}>
              <rect x={n.x0} y={n.y0} width={n.x1 - n.x0} height={n.y1 - n.y0} fill={color} rx={2} />
              <text x={labelX} y={midY - 5} textAnchor={anchor} fontSize={11} fill={isDarkMode() ? "#c4ccd8" : "#374151"} fontWeight={500}>
                {n.name}
              </text>
              <text x={labelX} y={midY + 8} textAnchor={anchor} fontSize={10} fill={isDarkMode() ? "#8f99a8" : "#6b7280"}>
                {fmt2(n.value)}
              </text>
            </g>
          );
        })}
      </svg>

    </div>
  );
}

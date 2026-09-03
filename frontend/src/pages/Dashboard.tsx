import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { accountsApi, cardsApi, recurringApi, analyticsApi, budgetApi, forecastApi } from "../api";
import { fmt, utilColor, utilBg, firstOfMonth, today } from "../lib/utils";
import { useBalancesHidden, maskIfHidden } from "../store/balanceVisibility";
import { useIsDarkMode } from "../store/theme";
import { CreditCard, Calendar, AlertCircle, AlertTriangle, Wallet, BookOpen, HelpCircle, TrendingUp } from "lucide-react";
import { AreaChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import HelpPanel from "../components/HelpPanel";
import { TrendBadge } from "../components/TrendBadge";
import { SparkLine } from "../components/SparkLine";
import { RiskBanner } from "../components/RiskBanner";
import { PlannedTransferReminder } from "../components/PlannedTransferReminder";
import { VerificationFlagButton } from "../components/VerificationFlagButton";

const DASHBOARD_HELP = `The Dashboard gives you a real-time snapshot of your financial health.

Key sections:
• Available to Spend — income minus bills minus what you've already spent
• Account balances — all checking and savings accounts
• Credit card balances and amounts due
• Monthly narrative summary — plain-English recap
• Upcoming bills — items due in the next 30 days`;

export default function Dashboard() {
  const navigate = useNavigate();
  const balancesHidden = useBalancesHidden();
  const [showHelp, setShowHelp] = useState(false);
  // Backend already returns the digest's top categories highest-first --
  // this just re-orders that same top-5 set alphabetically on request,
  // matching Securo's "Highest first" sort control. Doesn't re-select which
  // 5 categories show, only how they're listed.
  const [categorySortAlpha, setCategorySortAlpha] = useState(false);
  const [snapshotHelp, setSnapshotHelp] = useState<"spendable" | "margin" | null>(null);
  const [editingPending, setEditingPending] = useState<number | null>(null);
  const [pendingValue, setPendingValue] = useState("");
  const qc = useQueryClient();
  const updatePendingMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: object }) => cardsApi.update(id, data),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ["credit-cards"] });
      qc.invalidateQueries({ queryKey: ["budget-snapshot"] });
      qc.invalidateQueries({ queryKey: ["forecast-quarters"] });
      qc.invalidateQueries({ queryKey: ["forecast-multi-year"] });
      qc.invalidateQueries({ queryKey: ["forecast-risk"] });
      setEditingPending((current) => (current === variables.id ? null : current));
    },
  });
  const now = new Date();
  // Show previous month's summary once we're past the 3rd of the current month; otherwise current month
  const summaryMonth = now.getDate() > 3 ? now.getMonth() + 1 : (now.getMonth() === 0 ? 12 : now.getMonth());
  const summaryYear = now.getDate() > 3 ? now.getFullYear() : (now.getMonth() === 0 ? now.getFullYear() - 1 : now.getFullYear());

  const { data: accounts = [] } = useQuery<any[]>({ queryKey: ["accounts"], queryFn: accountsApi.list });
  const checkingAccounts = accounts.filter((a) => a.type === "checking");
  const { data: cards = [] } = useQuery<any[]>({ queryKey: ["credit-cards"], queryFn: cardsApi.list });
  const { data: recurring = [] } = useQuery<any[]>({ queryKey: ["recurring"], queryFn: () => recurringApi.list(true) });
  const { data: ats } = useQuery<any>({ queryKey: ["available-to-spend"], queryFn: analyticsApi.availableToSpend });
  const { data: summary } = useQuery<any>({
    queryKey: ["monthly-summary", summaryYear, summaryMonth],
    queryFn: () => analyticsApi.monthlySummary(summaryYear, summaryMonth),
  });
  const { data: rollingRaw = [] } = useQuery<{ month: string; total: string }[]>({
    queryKey: ["rolling-monthly-6"],
    queryFn: () => analyticsApi.rollingMonthly(6),
  });
  const primaryChecking = checkingAccounts[0];
  const { data: weeklyDigest } = useQuery<any>({
    queryKey: ["weekly-digest", primaryChecking?.id],
    queryFn: () => analyticsApi.weeklyDigest(primaryChecking.id),
    enabled: !!primaryChecking,
  });
  // Reuses the same day-by-day forecast walk everything else on this app
  // is built on (backend/services/forecast_engine.py) rather than
  // re-deriving a running balance from raw transactions on the frontend --
  // that engine has had five hard-won correctness fixes this session, and
  // duplicating its math here would duplicate its bug surface too. For a
  // month-to-date range, every entry through today is a real actual
  // balance, not a projection.
  const monthStart = firstOfMonth();
  const todayStr = today();
  const { data: balanceFlow = [] } = useQuery<any[]>({
    queryKey: ["dashboard-balance-flow", primaryChecking?.id, monthStart, todayStr],
    queryFn: () => forecastApi.range(primaryChecking.id, monthStart, todayStr),
    enabled: !!primaryChecking,
  });
  // Last month's FULL range (not just up to today's day-of-month) -- shown
  // as a reference line the whole way across, so the chart has something to
  // compare against on day 1 of a new month instead of rendering nothing
  // (the old guard, balanceFlow.length > 1, meant the card was invisible on
  // the 1st -- see commit 0bed663's comment). Dan's own reference for this
  // (2026-09-02): a dashboard chart overlaying the current month's live
  // line against last month's completed one, keyed by day-of-month rather
  // than calendar date so the two lines compare apples to apples.
  const lastMonthRange = (() => {
    const d = new Date();
    const lastMonthEnd = new Date(d.getFullYear(), d.getMonth(), 0); // day 0 of this month = last day of prior month
    const lastMonthStart = new Date(lastMonthEnd.getFullYear(), lastMonthEnd.getMonth(), 1);
    const iso = (dt: Date) => `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
    return { start: iso(lastMonthStart), end: iso(lastMonthEnd) };
  })();
  const { data: lastMonthFlow = [] } = useQuery<any[]>({
    queryKey: ["dashboard-balance-flow-prior", primaryChecking?.id, lastMonthRange.start, lastMonthRange.end],
    queryFn: () => forecastApi.range(primaryChecking.id, lastMonthRange.start, lastMonthRange.end),
    enabled: !!primaryChecking,
  });
  const isDark = useIsDarkMode();
  const { data: snapshot } = useQuery<any>({
    queryKey: ["budget-snapshot", primaryChecking?.id],
    queryFn: () => analyticsApi.budgetSnapshot(primaryChecking.id),
    enabled: !!primaryChecking,
  });
  const { data: budgetOverview = [] } = useQuery<any[]>({
    queryKey: ["budget-overview", now.getFullYear(), now.getMonth() + 1],
    queryFn: () => budgetApi.overview(now.getFullYear(), now.getMonth() + 1),
  });
  const budgetByCategory = new Map(budgetOverview.map((r: any) => [r.category_id, r]));

  const totalChecking = checkingAccounts.reduce((s: number, a: any) => s + parseFloat(a.current_balance), 0);
  const anyBelowThreshold = checkingAccounts.some((a: any) =>
    a.low_balance_threshold != null && parseFloat(a.current_balance) < parseFloat(a.low_balance_threshold)
  );
  const totalCardsDue = cards.reduce((s: number, c: any) => s + parseFloat(c.balance_due), 0);

  // Upcoming bills in next 30 days
  const todayDate = new Date();
  const upcoming = recurring
    .filter((r) => r.type === "expense")
    .map((r: any) => {
      const dom = r.day_of_month === 0 ? new Date(todayDate.getFullYear(), todayDate.getMonth() + 1, 0).getDate() : r.day_of_month;
      const next = new Date(todayDate.getFullYear(), todayDate.getMonth(), dom);
      if (next < todayDate) next.setMonth(next.getMonth() + 1);
      return { ...r, next_date: next };
    })
    .filter((r) => (r.next_date.getTime() - todayDate.getTime()) / 86400000 <= 30)
    .sort((a, b) => a.next_date.getTime() - b.next_date.getTime());


  // Sparkline + month-over-month % for the Net Position card.
  const rolling = [...rollingRaw].sort((a, b) => a.month.localeCompare(b.month));
  const sparkData = rolling.map((r) => parseFloat(r.total));
  const momPct: number | null = rolling.length >= 2
    ? (() => {
        const cur = parseFloat(rolling[rolling.length - 1].total);
        const prev = parseFloat(rolling[rolling.length - 2].total);
        return prev === 0 ? null : ((cur - prev) / prev) * 100;
      })()
    : null;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 flex items-center gap-1.5">Dashboard <button onClick={() => setShowHelp(true)} className="text-gray-400 hover:text-indigo-500 font-normal"><HelpCircle size={15} /></button></h2>
        <p className="text-sm text-gray-500">{new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" })}</p>
      </div>

      {/* Anything asking for an action goes first. These were sitting below
          the digest, so a transfer waiting to be scheduled was easy to scroll
          past on a page whose top half is reference figures. */}
      {weeklyDigest?.risk && <RiskBanner risk={weeklyDigest.risk} />}
      <PlannedTransferReminder />

      {/* Wide screens gain a COLUMN, not width. These panels are label/value
          lists and short prose, so stretching two of them to 900px only pads
          them -- the third slot pulls a panel up from below instead.
          At the widest breakpoint, Net Position joins as a 4th, narrower
          bookend alongside Available to Spend (Dan, 2026-09-02) -- both are
          compact label/value lists, so both get less width than Household
          Snapshot and Month in Review, which actually need the room. */}
      {(ats || snapshot) && (
        <div className="grid md:grid-cols-2 2xl:grid-cols-[0.85fr_1.15fr_1.15fr_0.85fr] gap-6">
          {ats && (
            <div className="card bg-gradient-to-br from-indigo-50 to-blue-50 border-indigo-100 dark:from-indigo-950/40 dark:to-blue-950/40 dark:border-indigo-900/50">
              <div className="flex items-center gap-2 mb-3">
                <Wallet size={16} className="text-indigo-500" />
                <h3 className="font-semibold text-gray-900 dark:text-white">
                  Available to Spend —{" "}
                  {new Date().toLocaleDateString("en-US", { month: "long" })}
                </h3>
              </div>
              <div className="space-y-1 text-sm">
                <div className="flex justify-between gap-4 text-gray-600 dark:text-gray-400">
                  <span>Monthly Income</span>
                  <span className="tabular-nums text-green-600 dark:text-green-400 font-medium">{fmt(parseFloat(ats.monthly_income))}</span>
                </div>
                <div className="flex justify-between gap-4 text-gray-600 dark:text-gray-400">
                  <span>Committed Bills</span>
                  <span className="tabular-nums text-red-500 dark:text-red-400 font-medium">−{fmt(parseFloat(ats.committed_expenses))}</span>
                </div>
                <div className="flex justify-between gap-4 text-gray-600 dark:text-gray-400">
                  <span>Spent So Far</span>
                  <span className="tabular-nums text-amber-600 dark:text-amber-400 font-medium">−{fmt(parseFloat(ats.spent_this_month))}</span>
                </div>
                <div className="border-t border-gray-200 dark:border-gray-700 mt-2 pt-2 flex justify-between gap-4">
                  <span className="font-semibold text-gray-900 dark:text-white">Available</span>
                  <span className={`tabular-nums text-lg font-bold ${parseFloat(ats.available) >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                    {fmt(parseFloat(ats.available))}
                  </span>
                </div>
              </div>
            </div>
          )}

          {snapshot && (
            <div className="card bg-gradient-to-br from-emerald-50 to-teal-50 border-emerald-100 dark:from-emerald-950/40 dark:to-teal-950/40 dark:border-emerald-900/50">
              <div className="flex items-center gap-2 mb-3">
                <Wallet size={16} className="text-emerald-600" />
                <h3 className="font-semibold text-gray-900 dark:text-white">Household Snapshot</h3>
                <VerificationFlagButton
                  feature="household_snapshot"
                  referenceType="account"
                  referenceId={primaryChecking?.id}
                  observed={{
                    left_to_spend: snapshot.left_to_spend,
                    left_to_spend_weekly: snapshot.left_to_spend_weekly,
                    safety_margin: snapshot.safety_margin,
                    safety_margin_weekly: snapshot.safety_margin_weekly,
                  }}
                  expectedFields={[
                    { key: "left_to_spend", label: "Left to Spend (monthly)" },
                    { key: "safety_margin", label: "Safety Margin (monthly)" },
                  ]}
                  className="ml-auto"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="text-center p-3 bg-white/60 dark:bg-black/20 rounded-lg">
                  <p className="text-xs text-gray-500 dark:text-gray-400 mb-1 flex items-center justify-center gap-1">
                    Spendable this week
                    <button onClick={() => setSnapshotHelp("spendable")} className="text-gray-300 hover:text-indigo-500 dark:text-gray-400 dark:hover:text-indigo-400" aria-label="What is Spendable this week?">
                      <HelpCircle size={12} />
                    </button>
                  </p>
                  <p className={`text-xl font-bold tabular-nums ${snapshot.on_pace ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>{fmt(parseFloat(snapshot.left_to_spend_weekly))}</p>
                  <p className={`text-xs mt-1 ${snapshot.on_pace ? "text-emerald-500 dark:text-emerald-400" : "text-red-500 dark:text-red-400"}`}>
                    {/* Signed, not Math.abs(). When the week is overspent this
                        figure is how much a day must come BACK, and stripping
                        the minus rendered an over-pace deficit as a positive
                        daily allowance -- the opposite of what it means, on the
                        one number the household reads before spending. */}
                    {parseFloat(snapshot.spendable_today) < 0 ? "−" : ""}{fmt(Math.abs(parseFloat(snapshot.spendable_today)))}/day · {snapshot.on_pace ? "on pace" : "over pace"}
                  </p>
                  {/* Weekly is this figure prorated by the share of the month
                      remaining -- same method the spreadsheet uses, so the two
                      lines are one calculation at two scales. */}
                  <p className="text-xs text-gray-400 mt-1">{fmt(parseFloat(snapshot.left_to_spend))} this month</p>
                </div>
                <div className="text-center p-3 bg-white/60 dark:bg-black/20 rounded-lg">
                  <p className="text-xs text-gray-500 dark:text-gray-400 mb-1 flex items-center justify-center gap-1">
                    Safety Margin (this week)
                    <button onClick={() => setSnapshotHelp("margin")} className="text-gray-300 hover:text-indigo-500 dark:text-gray-400 dark:hover:text-indigo-400" aria-label="What is Safety Margin?">
                      <HelpCircle size={12} />
                    </button>
                  </p>
                  <p className={`text-xl font-bold tabular-nums ${parseFloat(snapshot.safety_margin_weekly) < 0 ? "text-red-600 dark:text-red-400" : "text-amber-600 dark:text-amber-400"}`}>{fmt(parseFloat(snapshot.safety_margin_weekly))}</p>
                  <p className="text-xs text-gray-400 mt-1">{fmt(parseFloat(snapshot.safety_margin))} this month</p>
                  {/* The other decision boundary: below zero the plan already
                      runs into savings, so money has to come back out. */}
                  {parseFloat(snapshot.savings_pull_needed) > 0 && (
                    <p className="text-[11px] text-red-600 dark:text-red-400 mt-1.5 leading-snug">
                      Pull {fmt(parseFloat(snapshot.savings_pull_needed))} from savings
                    </p>
                  )}
                </div>
              </div>
              {snapshot.lookahead_minimum_date && (
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-3 text-center">
                  Lowest projected balance in the next 3 months:{" "}
                  <span className={`font-semibold tabular-nums ${parseFloat(snapshot.lookahead_minimum) < 0 ? "text-red-600 dark:text-red-400" : "text-gray-700 dark:text-gray-200"}`}>
                    {fmt(parseFloat(snapshot.lookahead_minimum))}
                  </span>{" "}
                  on {new Date(snapshot.lookahead_minimum_date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                </p>
              )}
            </div>
          )}
      {/* Spans the row while the band is two-up: wrapping alone into a
          half-width slot left the other half empty. */}
      {summary && (
        <div className="card md:col-span-2 2xl:col-span-1">
          <div className="flex items-center gap-2 mb-2">
            <BookOpen size={16} className="text-indigo-500" />
            <h3 className="font-semibold text-gray-900 dark:text-white">
              Month in Review —{" "}
              {new Date(summaryYear, summaryMonth - 1, 1).toLocaleDateString("en-US", { month: "long", year: "numeric" })}
            </h3>
          </div>
          <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed">{summary.text}</p>
          {summary.top_category && (
            <div className="mt-3 flex flex-wrap gap-4 text-xs text-gray-500 dark:text-gray-400 border-t border-gray-100 dark:border-gray-700 pt-3">
              <span>Top category: <span className="font-medium text-gray-700 dark:text-gray-300">{summary.top_category}</span></span>
              {summary.mom_delta_pct != null && (
                <span>
                  vs last month:{" "}
                  <span className={`font-medium ${parseFloat(summary.mom_delta_pct) > 0 ? "text-red-500" : "text-green-500"}`}>
                    {parseFloat(summary.mom_delta_pct) > 0 ? "+" : ""}{parseFloat(summary.mom_delta_pct).toFixed(1)}%
                  </span>
                </span>
              )}
              <span>
                Net cash flow:{" "}
                <span className={`font-medium ${parseFloat(summary.net_cashflow) >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                  {fmt(Math.abs(parseFloat(summary.net_cashflow)))} {parseFloat(summary.net_cashflow) >= 0 ? "surplus" : "deficit"}
                </span>
              </span>
            </div>
          )}
        </div>
      )}

      {/* Checking / Credit Card Balance / Amount Due dropped (Dan,
          2026-09-02): all three already live on the sidebar accounts list
          and the Credit Cards page respectively, and the 4-up grid was
          overflowing off-screen. Net Position is the one figure not shown
          as a single number anywhere else, so it stays -- as the narrow
          bookend on the far right of this row rather than its own. */}
      <div className={`stat-card animate-fade-slide-up animate-delay-100 ${totalChecking - totalCardsDue >= 0 ? "stat-card-accent-green" : "stat-card-accent-red"}`}>
        <span className="stat-label">Net Position</span>
        <span className={`stat-value ${totalChecking - totalCardsDue >= 0 ? "text-green-600" : "text-red-600"}`}>
          {anyBelowThreshold && <AlertTriangle size={18} className="text-amber-500 inline mr-1" />}
          {maskIfHidden(balancesHidden, fmt(totalChecking - totalCardsDue))}
        </span>
        <span className="text-xs text-gray-500">checking minus due</span>
        <div className="flex items-center justify-between mt-1">
          <TrendBadge pct={momPct} inverse />
          <SparkLine data={sparkData} color={totalChecking - totalCardsDue >= 0 ? "#22c55e" : "#ef4444"} />
        </div>
      </div>
        </div>
      )}

      {(balanceFlow.length > 0 || lastMonthFlow.length > 0) && (() => {
        // Keyed by day-of-month, not calendar date, so this month's
        // still-building line and last month's completed one compare on
        // the same X position (Dan's reference, 2026-09-02) rather than
        // needing two different date ranges lined up by hand.
        const byDay = new Map<number, { day: number; thisMonth?: number; lastMonth?: number }>();
        for (const e of lastMonthFlow) {
          const day = parseInt(e.date.slice(-2), 10);
          byDay.set(day, { day, lastMonth: parseFloat(e.projected_balance) });
        }
        for (const e of balanceFlow) {
          const day = parseInt(e.date.slice(-2), 10);
          const row = byDay.get(day) ?? { day };
          row.thisMonth = parseFloat(e.projected_balance);
          byDay.set(day, row);
        }
        const chartData = [...byDay.values()].sort((a, b) => a.day - b.day);

        const first = balanceFlow.length ? parseFloat(balanceFlow[0].projected_balance) : null;
        const last = balanceFlow.length ? parseFloat(balanceFlow[balanceFlow.length - 1].projected_balance) : null;
        const delta = first != null && last != null ? last - first : null;

        const lastMonthName = new Date(lastMonthRange.start + "T12:00:00").toLocaleDateString("en-US", { month: "long" });
        const thisMonthName = new Date(monthStart + "T12:00:00").toLocaleDateString("en-US", { month: "long" });
        const todayDay = parseInt(todayStr.slice(-2), 10);
        const sameDayLastMonth = lastMonthFlow.find((e: any) => parseInt(e.date.slice(-2), 10) === todayDay);
        const sameDayPct = sameDayLastMonth && last != null
          ? (() => {
              const priorVal = parseFloat(sameDayLastMonth.projected_balance);
              return priorVal === 0 ? null : ((last - priorVal) / Math.abs(priorVal)) * 100;
            })()
          : null;

        const lineColor = isDark ? "#a5b4fc" : "#6366f1";
        const priorLineColor = isDark ? "#5b6577" : "#9ca3af";
        return (
          <div className="card">
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3 className="font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2"><TrendingUp size={16} className="text-indigo-500" /> Balance Flow</h3>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  {thisMonthName} so far, vs. all of {lastMonthName}
                </p>
              </div>
              {delta != null && (
                <span className={`text-xl font-bold tabular-nums ${delta >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                  {maskIfHidden(balancesHidden, `${delta >= 0 ? "+" : "−"}${fmt(Math.abs(delta))}`)}
                </span>
              )}
            </div>
            <ResponsiveContainer width="100%" height={200}>
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
                  formatter={(v: number, name: string) => [maskIfHidden(balancesHidden, fmt(v)), name === "thisMonth" ? thisMonthName : lastMonthName]}
                  labelFormatter={(d: number) => `Day ${d}`}
                />
                <Area type="monotone" dataKey="thisMonth" stroke={lineColor} strokeWidth={2} fill="url(#balanceFlowGradient)" dot={false} connectNulls animationDuration={700} animationEasing="ease-out" />
                <Line type="monotone" dataKey="lastMonth" stroke={priorLineColor} strokeWidth={1.5} strokeDasharray="4 3" dot={false} connectNulls isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
            {sameDayLastMonth && sameDayPct != null && (
              <p className="text-xs text-gray-400 mt-2">
                In {lastMonthName} on day {todayDay}: {maskIfHidden(balancesHidden, fmt(parseFloat(sameDayLastMonth.projected_balance)))}
                {" "}({sameDayPct >= 0 ? "+" : ""}{sameDayPct.toFixed(1)}%)
              </p>
            )}
          </div>
        );
      })()}

      {weeklyDigest && (
        <div className="card">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-1">
            Weekly Digest — {new Date(weeklyDigest.week_start + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
            {" – "}
            {new Date(weeklyDigest.week_end + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
          </h3>
          <p className="text-sm text-gray-500 mb-3">Total spent: <span className="font-semibold text-gray-900 dark:text-gray-100">{fmt(parseFloat(weeklyDigest.total_spent))}</span></p>

          <div className="grid md:grid-cols-2 gap-6">
            {weeklyDigest.categories.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-2 pb-1 border-b-2 border-indigo-100 dark:border-indigo-900/50">
                  <p className="text-xs font-bold text-indigo-600 dark:text-indigo-300 uppercase tracking-wider">By Category</p>
                  <button
                    onClick={() => setCategorySortAlpha(v => !v)}
                    className="text-[11px] font-medium text-gray-400 dark:text-gray-500 hover:text-indigo-600 dark:hover:text-indigo-300"
                  >
                    {categorySortAlpha ? "A–Z" : "Highest first"}
                  </button>
                </div>
                <div className="space-y-1.5 text-sm">
                  {(categorySortAlpha
                    ? [...weeklyDigest.categories.slice(0, 5)].sort((a: any, b: any) => a.category_name.localeCompare(b.category_name))
                    : weeklyDigest.categories.slice(0, 5)
                  ).map((c: any) => {
                    const budget = budgetByCategory.get(c.category_id);
                    const budgeted = budget ? parseFloat(budget.budgeted) : 0;
                    const actual = budget ? parseFloat(budget.actual_total) : 0;
                    const pct = budgeted > 0 ? Math.min(100, (actual / budgeted) * 100) : 0;
                    const overBudget = budgeted > 0 && actual > budgeted;
                    return (
                      <div key={c.category_id} className={`relative rounded overflow-hidden ${budgeted > 0 ? `border-l-2 ${overBudget ? "border-red-500" : "border-indigo-400"}` : ""}`}>
                        {budgeted > 0 && (
                          <div
                            className={`absolute inset-y-0 left-0 ${overBudget ? "bg-red-200/70 dark:bg-red-900/40" : "bg-indigo-200/70 dark:bg-indigo-800/40"}`}
                            style={{ width: `${pct}%` }}
                          />
                        )}
                        <div className="relative flex justify-between gap-4 px-1.5 py-1 text-gray-600 dark:text-gray-400">
                          <span className="flex items-center gap-1 min-w-0 truncate">
                            {overBudget && <AlertTriangle size={11} className="text-red-500 shrink-0" />}
                            {c.category_name}
                          </span>
                          <span className="tabular-nums shrink-0">{fmt(parseFloat(c.total))}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {weeklyDigest.top_merchants.length > 0 && (
              <div>
                <p className="text-xs font-bold text-indigo-600 dark:text-indigo-300 uppercase tracking-wider mb-2 pb-1 border-b-2 border-indigo-100 dark:border-indigo-900/50">Top Merchants</p>
                <div className="space-y-1.5 text-sm">
                  {weeklyDigest.top_merchants.slice(0, 5).map((m: any) => (
                    <div key={m.name} className="flex justify-between gap-4 px-1.5 py-1 text-gray-600 dark:text-gray-400">
                      <span className="truncate">{m.name}</span>
                      <span className="tabular-nums shrink-0">{fmt(parseFloat(m.total))}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}


      {/* Same idea: a third column rather than two stretched ones, so
          All Accounts rises out of the tail of the page. */}
      <div className="grid md:grid-cols-2 2xl:grid-cols-3 gap-6">
        {/* Credit cards */}
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-gray-900 flex items-center gap-2"><CreditCard size={16} /> Credit Cards</h3>
            <button onClick={() => navigate("/credit-cards")} className="text-xs text-indigo-600 hover:underline">Manage →</button>
          </div>
          {cards.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-4">No credit cards added yet</p>
          ) : (
            <div className="space-y-3 max-h-80 overflow-y-auto pr-1">
              {cards.map((c: any) => (
                <div key={c.id} className="flex items-center justify-between">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{c.name}</p>
                    <p className="text-xs text-gray-500">
                      {c.last_four && `••• ${maskIfHidden(balancesHidden, c.last_four)} · `}Due day {c.due_day}
                    </p>
                    <div className="mt-1 w-32">
                      <div className="progress-bar">
                        <div
                          className={`progress-fill ${utilBg(c.utilization_pct)}`}
                          style={{ width: `${Math.min(100, c.utilization_pct)}%` }}
                        />
                      </div>
                    </div>
                    <div className="mt-1 text-xs text-gray-500">
                      {editingPending === c.id ? (
                        <span className="inline-flex items-center gap-1">
                          Pending:
                          <input
                            type="number" step="0.01" autoFocus
                            className="input !w-20 !py-0.5 !text-xs"
                            value={pendingValue}
                            onChange={(e) => setPendingValue(e.target.value)}
                            onBlur={() => updatePendingMut.mutate({ id: c.id, data: { pending_charges: parseFloat(pendingValue) || 0 } })}
                            onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                          />
                        </span>
                      ) : (
                        <button
                          className="hover:underline"
                          onClick={() => { setEditingPending(c.id); setPendingValue(c.pending_charges || "0"); }}
                        >
                          Pending: {fmt(c.pending_charges || 0)} ✎
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="text-right shrink-0 ml-4">
                    <p className={`text-sm font-bold tabular-nums ${utilColor(c.utilization_pct)}`}>{maskIfHidden(balancesHidden, fmt(c.current_balance))}</p>
                    <p className="text-xs text-gray-500">{c.utilization_pct}% of {maskIfHidden(balancesHidden, fmt(c.credit_limit))}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Upcoming bills */}
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-gray-900 flex items-center gap-2"><Calendar size={16} /> Upcoming Bills</h3>
            <button onClick={() => navigate("/recurring")} className="text-xs text-indigo-600 hover:underline">Manage →</button>
          </div>
          {upcoming.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-4">No recurring bills set up</p>
          ) : (
            <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
              {upcoming.slice(0, 8).map((r: any) => {
                const daysUntil = Math.ceil((r.next_date.getTime() - todayDate.getTime()) / 86400000);
                return (
                  <div key={r.id} className="flex items-center justify-between py-1">
                    <div>
                      <p className="text-sm font-medium text-gray-900">{r.name}</p>
                      <p className="text-xs text-gray-500">
                        {r.next_date.toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                        {" · "}
                        <span className={daysUntil <= 3 ? "text-red-600 font-medium" : "text-gray-400"}>
                          {daysUntil === 0 ? "Today" : daysUntil === 1 ? "Tomorrow" : `${daysUntil} days`}
                        </span>
                      </p>
                    </div>
                    <span className="text-sm font-semibold text-red-600 tabular-nums">{fmt(r.amount)}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      {accounts.length > 0 && (
        <div className="card md:col-span-2 2xl:col-span-1">
          <h3 className="font-semibold text-gray-900 mb-4">All Accounts</h3>
          <div className="divide-y divide-gray-100 max-h-80 overflow-y-auto pr-1">
            {accounts.map((a: any) => (
              <div key={a.id} className="flex items-center justify-between gap-4 py-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-900 truncate">{a.name}</p>
                  <p className="text-xs text-gray-500 capitalize">{a.type.replace("_", " ")}</p>
                </div>
                <span className={`text-sm font-bold tabular-nums shrink-0 ${parseFloat(a.current_balance) >= 0 ? "text-gray-900" : "text-red-600"}`}>
                  {a.low_balance_threshold != null && parseFloat(a.current_balance) < parseFloat(a.low_balance_threshold) && (
                    <AlertTriangle size={14} className="text-amber-500 inline mr-1" />
                  )}
                  {maskIfHidden(balancesHidden, fmt(a.current_balance))}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      </div>

      {/* Empty state for new users */}
      {accounts.length === 0 && recurring.length === 0 && (
        <div className="card text-center py-10">
          <AlertCircle className="mx-auto text-indigo-300 mb-3" size={40} />
          <h3 className="font-semibold text-gray-700 mb-1">Welcome to OfflineBudget!</h3>
          <p className="text-sm text-gray-500 mb-4">Start by adding your checking account and recurring income/bills.</p>
          <div className="flex gap-3 justify-center">
            <button onClick={() => navigate("/settings/accounts")} className="btn-primary">Add Account</button>
            <button onClick={() => navigate("/recurring")} className="btn-secondary">Add Recurring Items</button>
          </div>
        </div>
      )}
      {showHelp && <HelpPanel title="Dashboard" body={DASHBOARD_HELP} onClose={() => setShowHelp(false)} />}
      {snapshotHelp === "spendable" && (
        <HelpPanel
          title="Spendable this week"
          body={"How much you can spend on everyday things (groceries, eating out, shopping) between now and the end of the week, after bills, savings, and tithing are already set aside.\n\nGoes down as you spend. If it's negative, you've spent more than this week's share — it'll say \"over pace\" and show what to pull back."}
          onClose={() => setSnapshotHelp(null)}
        />
      )}
      {snapshotHelp === "margin" && (
        <HelpPanel
          title="Safety Margin"
          body={"The lowest your checking account is projected to go over the next 3 months, after also setting aside the credit card bills still coming due this month.\n\nPositive means that's how much room you have above $0 before you'd need to pull from savings. Negative means the plan already dips into savings, even before anything unexpected happens — worth a closer look before a big purchase."}
          onClose={() => setSnapshotHelp(null)}
        />
      )}
    </div>
  );
}

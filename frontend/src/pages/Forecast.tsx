import { useState } from "react";
import { useQuery, useQueries, useMutation, useQueryClient } from "@tanstack/react-query";
import { accountsApi, forecastApi, scenariosApi, plannedExpensesApi, authApi, cardsApi, dayCheckpointsApi, transactionsApi, categoriesApi, plannedTransfersApi } from "../api";
import { fmt, today } from "../lib/utils";
import { Link } from "react-router-dom";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Legend, BarChart, Bar, ComposedChart } from "recharts";
import { ChevronDown, ChevronUp, AlertTriangle, Plus, Trash2, X, TrendingUp, HelpCircle, CreditCard, Pencil, ShieldCheck } from "lucide-react";
import HelpPanel from "../components/HelpPanel";
import MonthlyAccuracyRow from "../components/MonthlyAccuracyRow";
import { RiskBanner } from "../components/RiskBanner";
import { PlannedTransferReminder } from "../components/PlannedTransferReminder";
import { sortCategoryList, byName } from "../lib/selectOptions";

function isDarkMode(): boolean {
  return document.documentElement.classList.contains("dark");
}

function chartTheme() {
  const dark = isDarkMode();
  return {
    grid:    dark ? "#3a4051" : "#e5e7eb",
    tick:    dark ? "#8f99a8" : "#6b7280",
    tooltip: dark ? "#2a2f3d" : "#ffffff",
    tooltipBorder: dark ? "#3a4051" : "#e5e7eb",
    tooltipText: dark ? "#c4ccd8" : "#111827",
    // Recharts paints legend labels in the series colour, so indigo-500 --
    // fine as a stroke -- rendered legend text at 3.5:1 in dark mode. The
    // 400 weight reads at 5.25:1 and is barely different as a line.
    series:  dark ? "#a5b4fc" : "#6366f1",
    series2: dark ? "#34d399" : "#10b981",
  };
}

const emptyExpense = { name: "", amount: "", expected_date: today(), notes: "", account_id: "", card_id: "", direction: "outflow", funding_account_id: "", funding_amount: "", funding_lead_days: "1" };

export default function Forecast() {
  const qc = useQueryClient();
  const { data: accounts = [] } = useQuery({ queryKey: ["accounts"], queryFn: accountsApi.list });
  const checkingAccounts = byName(accounts.filter((a: any) => a.type === "checking"));
  // Anything that isn't the spending account can fund a purchase -- savings,
  // money market, a brokerage sweep. Emergency funds included: it's Dan's
  // money and his call, the flag only governs "available savings" reporting.
  const fundingAccounts = byName(accounts.filter((a: any) => a.type !== "checking"));
  // Savings shown as bars behind the checking line: the two are read together
  // (can I cover this, and what does it cost the cushion?) but live on wildly
  // different scales, so they share an X axis and not a Y.
  //
  // Savings-type accounts only. Money market is deliberately excluded --
  // Dan's is an emergency fund, and folding it in inflated the series by
  // ~$26k of money he has no intention of spending, which is the same reason
  // it is already held out of available-savings reporting.
  const savingsAccounts = accounts.filter(
    (a: any) => a.is_active !== false && a.type === "savings",
  );
  const [showSavings, setShowSavings] = useState(true);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [year, setYear] = useState(new Date().getFullYear());
  const [forecastYears, setForecastYears] = useState(1);
  const [expandedQ, setExpandedQ] = useState<number | null>(null);
  const [scenarioId, setScenarioId] = useState<number | null>(null);
  const [chartView, setChartView] = useState<"balance" | "net">("balance");
  const [showHelp, setShowHelp] = useState(false);
  const [showExpenseForm, setShowExpenseForm] = useState(false);
  const [expenseForm, setExpenseForm] = useState({ ...emptyExpense });
  const [editExpenseId, setEditExpenseId] = useState<number | null>(null);
  const [editExpenseForm, setEditExpenseForm] = useState({ ...emptyExpense });
  const [dayCheckpoint, setDayCheckpoint] = useState<{ date: string; value: string } | null>(null);
  const [addTxnDate, setAddTxnDate] = useState<string | null>(null);
  const [addTxnForm, setAddTxnForm] = useState({ description: "", amount: "", category_id: "" });
  const [anchorValue, setAnchorValue] = useState("");
  const [anchorDismissed, setAnchorDismissed] = useState(false);
  const [yearStartValue, setYearStartValue] = useState("");
  const [yearStartDismissed, setYearStartDismissed] = useState(false);

  const activeAccountId = accountId ?? checkingAccounts[0]?.id;
  const activeAccount = checkingAccounts.find((a: any) => a.id === activeAccountId);
  const lowBalanceThreshold = activeAccount?.low_balance_threshold != null
    ? parseFloat(activeAccount.low_balance_threshold)
    : null;

  const { data: singleYearQuarters = [], isLoading: singleLoading } = useQuery({
    queryKey: ["forecast-quarters", activeAccountId, year],
    queryFn: () => forecastApi.quarters(activeAccountId, year),
    enabled: !!activeAccountId && forecastYears === 1,
  });
  const { data: multiYearQuarters = [], isLoading: multiLoading } = useQuery({
    queryKey: ["forecast-multi-year", activeAccountId, year, forecastYears],
    queryFn: () => forecastApi.multiYear(activeAccountId, year, forecastYears),
    enabled: !!activeAccountId && forecastYears > 1,
  });
  const quarters = forecastYears === 1 ? singleYearQuarters : multiYearQuarters;
  const isLoading = forecastYears === 1 ? singleLoading : multiLoading;

  // One forecast per savings account, summed. Dan holds Savings plus a Money
  // Market emergency fund; the emergency flag governs what counts as
  // *available* savings in reporting, not what he's allowed to look at, so
  // both are drawn here.
  // Earliest real transaction across the savings accounts. Before that date
  // the forecast reconstructs history by walking backward from today's
  // balance, which is accurate only where a full transaction history exists.
  // On an account synced for balance but not for history, that draws a
  // confident flat line at today's figure across months when the true balance
  // was very different -- a large transfer INTO savings makes everything
  // before it look far too high. Better to plot nothing than to assert that.
  const savingsHistoryQueries = useQueries({
    queries: savingsAccounts.map((a: any) => ({
      queryKey: ["savings-first-txn", a.id],
      queryFn: () => transactionsApi.list({ account_id: a.id, limit: 500 }),
      enabled: showSavings && savingsAccounts.length > 0,
    })),
  });
  const savingsHistoryStart = (() => {
    const dates: string[] = [];
    savingsHistoryQueries.forEach((q: any) => (q.data ?? []).forEach((x: any) => dates.push(x.date)));
    return dates.length ? dates.sort()[0] : null;
  })();

  const savingsQueries = useQueries({
    queries: savingsAccounts.map((a: any) => ({
      queryKey: ["forecast-quarters", a.id, year, forecastYears],
      queryFn: () => (forecastYears === 1
        ? forecastApi.quarters(a.id, year)
        : forecastApi.multiYear(a.id, year, forecastYears)),
      enabled: showSavings && savingsAccounts.length > 0,
    })),
  });
  // date -> combined savings balance. Every day is kept, not every third:
  // this is a lookup and the bar series samples it through chartData's own
  // filter, so extra keys are simply never read.
  const savingsByDate: Record<string, number> = {};
  savingsQueries.forEach((q: any) => {
    (q.data ?? []).forEach((quarter: any) =>
      (quarter.days ?? []).forEach((d: any) => {
        savingsByDate[d.date] = (savingsByDate[d.date] ?? 0) + parseFloat(d.projected_balance);
      })
    );
  });
  const hasSavingsSeries = showSavings && Object.keys(savingsByDate).length > 0;

  const { data: scenarios = [] } = useQuery({
    queryKey: ["scenarios"],
    queryFn: scenariosApi.list,
  });

  const { data: plannedExpenses = [] } = useQuery({
    queryKey: ["planned-expenses"],
    queryFn: () => plannedExpensesApi.list(false),
  });

  const { data: me } = useQuery({
    queryKey: ["me"],
    queryFn: authApi.me,
  });

  const { data: upcomingDue = [] } = useQuery<any[]>({
    queryKey: ["cards-upcoming-due"],
    queryFn: cardsApi.upcomingDue,
  });

  const { data: cards = [] } = useQuery<any[]>({
    queryKey: ["cards"],
    queryFn: cardsApi.list,
  });
  const activeCards = (cards as any[]).filter((c: any) => c.is_active);

  const { data: dayCheckpoints = [] } = useQuery<any[]>({
    queryKey: ["day-checkpoints", activeAccountId],
    queryFn: () => dayCheckpointsApi.list(activeAccountId!),
    enabled: !!activeAccountId,
  });

  const { data: risk } = useQuery({
    queryKey: ["forecast-risk", activeAccountId],
    queryFn: () => forecastApi.risk(activeAccountId),
    enabled: !!activeAccountId,
  });

  const { data: categories = [] } = useQuery<any[]>({
    queryKey: ["categories"],
    queryFn: categoriesApi.list,
  });

  const dayCheckpointMap: Record<string, number> = {};
  (dayCheckpoints as any[]).forEach((c: any) => {
    dayCheckpointMap[c.date] = parseFloat(c.actual_balance);
  });

  const allCatOptions = sortCategoryList((categories as any[]).flatMap((c: any) => [c, ...(c.children ?? [])]), categories as any[]);

  // Balance anchor banner: show when no day checkpoint exists for today and account is new or has never been verified
  const todayIso = today();
  const anchorDismissKey = `forecast-anchor-dismissed-${activeAccountId}`;
  const hasTodayCheckpoint = dayCheckpointMap[todayIso] !== undefined;
  const accountCreatedAt = activeAccount?.created_at ? new Date(activeAccount.created_at) : null;
  const accountIsNew = accountCreatedAt != null && (Date.now() - accountCreatedAt.getTime()) < 30 * 24 * 60 * 60 * 1000;
  const hasAnyCheckpoint = (dayCheckpoints as any[]).length > 0;
  const persistedDismiss = typeof window !== "undefined" && localStorage.getItem(anchorDismissKey) === "1";
  const showAnchorBanner = !anchorDismissed && !persistedDismiss && !hasTodayCheckpoint && (accountIsNew || !hasAnyCheckpoint);

  // Year-start balance banner: show when Jan 1 of the selected year is in the past and no checkpoint exists near it
  const janFirstIso = `${year}-01-01`;
  const yearStartDismissKey = `forecast-year-start-${year}-${activeAccountId}`;
  const hasYearStartCheckpoint = Object.keys(dayCheckpointMap).some(
    d => d >= janFirstIso && d <= `${year}-01-07`
  );
  const janFirstIsPast = new Date(year, 0, 1) < new Date(todayIso);
  const yearStartPersistedDismiss = typeof window !== "undefined" && localStorage.getItem(yearStartDismissKey) === "1";
  // Q1 open_balance is the reconstructed Jan 1 balance — use as the suggested value
  const q1OpenBalance = (quarters as any[]).find((q: any) => q.quarter === 1 && q.year === year)?.open_balance;
  const showYearStartBanner = janFirstIsPast && !hasYearStartCheckpoint && !yearStartDismissed && !yearStartPersistedDismiss && !!activeAccountId;

  const saveDayCheckpointMut = useMutation({
    mutationFn: ({ date, actual_balance }: { date: string; actual_balance: number }) =>
      dayCheckpointsApi.upsert(date, activeAccountId!, actual_balance),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["day-checkpoints"] });
      qc.invalidateQueries({ queryKey: ["forecast-quarters"] });
      qc.invalidateQueries({ queryKey: ["forecast-multi-year"] });
      setDayCheckpoint(null);
    },
  });

  const saveAnchorMut = useMutation({
    mutationFn: (balance: number) => dayCheckpointsApi.upsert(todayIso, activeAccountId!, balance, "Balance verified"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["day-checkpoints"] });
      qc.invalidateQueries({ queryKey: ["forecast-quarters"] });
      qc.invalidateQueries({ queryKey: ["forecast-multi-year"] });
      setAnchorValue("");
    },
  });

  const saveYearStartMut = useMutation({
    mutationFn: (balance: number) => dayCheckpointsApi.upsert(janFirstIso, activeAccountId!, balance, "Year opening balance"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["day-checkpoints"] });
      qc.invalidateQueries({ queryKey: ["forecast-quarters"] });
      qc.invalidateQueries({ queryKey: ["forecast-multi-year"] });
      setYearStartValue("");
      setYearStartDismissed(true);
    },
  });

  const deleteDayCheckpointMut = useMutation({
    mutationFn: (date: string) => dayCheckpointsApi.remove(date, activeAccountId!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["day-checkpoints"] });
      qc.invalidateQueries({ queryKey: ["forecast-quarters"] });
      qc.invalidateQueries({ queryKey: ["forecast-multi-year"] });
    },
  });

  const createTxnMut = useMutation({
    mutationFn: (data: object) => transactionsApi.create(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["forecast-quarters"] });
      qc.invalidateQueries({ queryKey: ["forecast-multi-year"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      setAddTxnDate(null);
      setAddTxnForm({ description: "", amount: "", category_id: "" });
    },
  });

  const acceptSuggestionMut = useMutation({
    mutationFn: (data: { to_account_id: number; from_account_id: number; amount: string; target_date: string; suggested: boolean }) =>
      plannedTransfersApi.create(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["planned-transfers"] });
      qc.invalidateQueries({ queryKey: ["forecast-risk"] });
      // The accepted transfer is injected into the day-by-day walk, so the
      // chart itself is stale until these refetch.
      qc.invalidateQueries({ queryKey: ["forecast-quarters"] });
      qc.invalidateQueries({ queryKey: ["forecast-multi-year"] });
    },
  });

  const today_date = new Date();
  const quarterEndDates: Record<number, Date> = {
    1: new Date(year, 2, 31),  // Mar 31
    2: new Date(year, 5, 30),  // Jun 30
    3: new Date(year, 8, 30),  // Sep 30
    4: new Date(year, 11, 31), // Dec 31
  };

  const createExpenseMut = useMutation({
    mutationFn: plannedExpensesApi.create,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["planned-expenses"] }); setShowExpenseForm(false); setExpenseForm({ ...emptyExpense }); },
  });
  // Settling a one-off closes the prediction against reality. Kept separate
  // from delete on purpose: deleting loses the estimate, and comparing the
  // estimate to what actually moved is how the next one gets better.
  const [settleId, setSettleId] = useState<number | null>(null);
  const [settleAmount, setSettleAmount] = useState("");
  const settleMut = useMutation({
    mutationFn: ({ id, actual }: { id: number; actual: number | null }) =>
      plannedExpensesApi.settle(id, actual),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["planned-expenses"] });
      qc.invalidateQueries({ queryKey: ["forecast"] });
      setSettleId(null);
      setSettleAmount("");
    },
  });

  const deleteExpenseMut = useMutation({
    mutationFn: plannedExpensesApi.remove,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["planned-expenses"] }),
  });
  const updateExpenseMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: object }) => plannedExpensesApi.update(id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["planned-expenses"] }); setEditExpenseId(null); },
  });

  const { data: scenarioQuarters = [] } = useQuery({
    queryKey: ["forecast-quarters-scenario", activeAccountId, year, scenarioId],
    queryFn: () => {
      const scenario = (scenarios as any[]).find((s: any) => s.id === scenarioId);
      if (!scenario) return [];
      const overrides = scenario.overrides.map((o: any) => ({
        recurring_item_id: o.recurring_item_id,
        amount_delta: parseFloat(o.amount_delta),
      }));
      return forecastApi.quartersWithScenario(activeAccountId, year, overrides);
    },
    enabled: !!activeAccountId && scenarioId !== null && (scenarios as any[]).some((s: any) => s.id === scenarioId),
  });

  // Baseline chart data split at today for actual vs projected
  const todayStr = today();
  // Sampled to every 3rd day to keep the line readable, but each quarter's
  // lowest-balance day is always kept. That trough is exactly what
  // /forecast/risk scans for, and dropping it meant the red banner could warn
  // about a dip that was invisible on the graph it sits above.
  const chartData = (quarters as any[]).flatMap((q: any) => {
    const lowest = (q.days as any[]).reduce(
      (lo: any, d: any) => (parseFloat(d.projected_balance) < parseFloat(lo.projected_balance) ? d : lo),
      q.days[0],
    );
    return (q.days as any[])
      .filter((d: any, i: number) => i % 3 === 0 || d.date === lowest?.date)
      .map((d: any) => {
        const balance = parseFloat(d.projected_balance);
        return {
          date: d.date,
          baseline: balance,
          actual: d.date <= todayStr ? balance : null,
          projected: d.date >= todayStr ? balance : null,
          label: new Date(d.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }),
        };
      });
  });

  // Merge scenario trace into chart data
  const scenarioMap: Record<string, number> = {};
  if (scenarioId !== null && (scenarioQuarters as any[]).length > 0) {
    // Every day, not every 3rd: this is a lookup keyed by date, and sampling it
    // separately from chartData left the scenario line with holes wherever the
    // two filters disagreed (which they now do, since chartData also keeps each
    // quarter's trough). Extra keys are simply never read.
    (scenarioQuarters as any[]).forEach((q: any) =>
      (q.days as any[]).forEach((d: any) => {
        scenarioMap[d.date] = parseFloat(d.projected_balance);
      })
    );
  }

  // One savings bar per month, not one per chart point. The balance line is
  // sampled every 3rd day, and hanging a bar off each of those put ~124
  // adjacent bars across a year -- they merged into a solid pale block that
  // read as a background fill and hid the gridlines behind it. A savings
  // balance moves on a monthly rhythm anyway, so the first sampled day of
  // each month carries the bar and the rest leave it undefined (Recharts
  // simply draws nothing there).
  const seenMonths = new Set<string>();
  const mergedData = chartData.map(d => {
    const month = d.date.slice(0, 7);
    let savings: number | undefined;
    // Today onward is a projection from the current balance, which is sound.
    // Earlier than the first known transaction is not.
    const plottable = d.date >= todayStr || (savingsHistoryStart != null && d.date >= savingsHistoryStart);
    if (hasSavingsSeries && plottable && !seenMonths.has(month)) {
      seenMonths.add(month);
      savings = savingsByDate[d.date];
    }
    return { ...d, scenario: scenarioMap[d.date] ?? undefined, savings };
  });

  const hasScenario = scenarioId !== null && Object.keys(scenarioMap).length > 0;

  // Net view: one bar per quarter
  const netBarData = (quarters as any[]).map((q: any) => ({
    name: forecastYears > 1 ? `Q${q.quarter} ${q.year}` : `Q${q.quarter}`,
    net: parseFloat(q.net),
    income: parseFloat(q.total_income),
    expenses: parseFloat(q.total_expenses),
  }));

  // SS limit: read the real crossing date off the forecast's own boosted
  // paychecks (is_ss_boosted) rather than re-deriving one client-side. The old
  // client model assumed a strict 14-day cadence from Jan 1 and ignored
  // paychecks already received, and landed two months early (July vs the
  // backend's real September) against Dan's actual semimonthly pay dates and
  // YTD wages. Found live 2026-08-12 comparing the rendered banner to the
  // fixed backend forecast.
  const ssGross = me?.ss_gross_per_paycheck ? parseFloat(me.ss_gross_per_paycheck) : null;
  const ssConfigured = ssGross !== null && ssGross > 0;
  let ssLimitMonth: string | null = null;
  let ssPerPaycheckIncrease: number | null = null;
  if (ssConfigured) {
    const boostedDay = (quarters as any[])
      .flatMap((q: any) => q.days as any[])
      .find((d: any) => (d.transactions as any[]).some((t: any) => t.is_ss_boosted));
    if (boostedDay) {
      ssLimitMonth = new Date(boostedDay.date + "T12:00:00").toLocaleDateString("en-US", { month: "long", year: "numeric" });
      ssPerPaycheckIncrease = ssGross! * 0.062;
    }
  }

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload?.length) {
      const nameMap: Record<string, string> = { actual: "Actual", projected: "Projected", scenario: "Scenario", baseline: "Balance", savings: "Savings" };
      return (
        <div className="card py-2 px-3 shadow-lg text-sm">
          <p className="text-gray-500 text-xs mb-1">{label}</p>
          {payload.filter((p: any) => p.value != null).map((p: any) => (
            <p key={p.dataKey} className="font-bold" style={{ color: p.color }}>
              {nameMap[p.dataKey] ?? p.dataKey}: {fmt(p.value)}
            </p>
          ))}
        </div>
      );
    }
    return null;
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-900 flex items-center gap-1.5">Forecast <button onClick={() => setShowHelp(true)} className="text-gray-400 hover:text-indigo-500 font-normal"><HelpCircle size={15} /></button></h2>
          <p className="text-sm text-gray-500">Day-by-day balance projection</p>
        </div>
        <div className="flex gap-2 flex-wrap items-center">
          {checkingAccounts.length > 1 ? (
            <select className="input w-auto" value={activeAccountId ?? ""} onChange={e => setAccountId(parseInt(e.target.value))}>
              {checkingAccounts.map((a: any) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          ) : activeAccount ? (
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300 px-1">{activeAccount.name}</span>
          ) : null}
          <select className="input w-auto" value={year} onChange={e => setYear(parseInt(e.target.value))}>
            {[-1, 0, 1, 2].map(d => <option key={d} value={new Date().getFullYear() + d}>{new Date().getFullYear() + d}</option>)}
          </select>
          <select className="input w-auto" value={forecastYears} onChange={e => setForecastYears(parseInt(e.target.value))}>
            <option value={1}>1 year</option>
            <option value={2}>2 years</option>
            <option value={3}>3 years</option>
            <option value={5}>5 years</option>
          </select>
          <select className="input w-auto" value={chartView} onChange={e => setChartView(e.target.value as "balance" | "net")}>
            <option value="balance">Running Balance</option>
            <option value="net">Net Income/Expense</option>
          </select>
          {(scenarios as any[]).length > 0 && (
            <select className="input w-auto" value={scenarioId ?? ""} onChange={e => setScenarioId(e.target.value === "" ? null : parseInt(e.target.value))}>
              <option value="">Baseline only</option>
              {(scenarios as any[]).map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          )}
        </div>
      </div>

      {checkingAccounts.length === 0 && (
        <div className="card text-center py-8 text-gray-400">Add a checking account to see your forecast.</div>
      )}

      {showAnchorBanner && activeAccount && (
        <div className="card border-indigo-200 dark:border-indigo-700 bg-indigo-50/60 dark:bg-indigo-900/20">
          <div className="flex items-start gap-3">
            <ShieldCheck size={18} className="text-indigo-500 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="font-semibold text-indigo-900 dark:text-indigo-200 text-sm">Confirm your current balance</p>
              <p className="text-xs text-indigo-700 dark:text-indigo-300 mt-0.5">
                Your account shows <strong>{fmt(activeAccount.current_balance)}</strong>. Does this match your bank right now?
                Setting today's balance anchors the forecast so projections start from a verified number.
              </p>
              <div className="flex items-center gap-2 mt-3">
                <input
                  type="number"
                  step="0.01"
                  className="input py-1 w-36 text-sm"
                  placeholder={String(parseFloat(activeAccount.current_balance).toFixed(2))}
                  value={anchorValue}
                  onChange={e => setAnchorValue(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === "Enter" && anchorValue) saveAnchorMut.mutate(parseFloat(anchorValue));
                  }}
                />
                <button
                  onClick={() => saveAnchorMut.mutate(parseFloat(anchorValue || activeAccount.current_balance))}
                  disabled={saveAnchorMut.isPending}
                  className="btn-primary text-xs px-3 py-1.5"
                >
                  {saveAnchorMut.isPending ? "Saving…" : "Confirm Balance"}
                </button>
                <button
                  onClick={() => { localStorage.setItem(anchorDismissKey, "1"); setAnchorDismissed(true); }}
                  className="text-xs text-indigo-400 hover:text-indigo-600 underline"
                >
                  Dismiss
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {showYearStartBanner && activeAccountId && (
        <div className="card border-amber-200 dark:border-amber-700 bg-amber-50/60 dark:bg-amber-900/20">
          <div className="flex items-start gap-3">
            <AlertTriangle size={18} className="text-amber-500 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="font-semibold text-amber-900 dark:text-amber-200 text-sm">Set your {year} opening balance</p>
              <p className="text-xs text-amber-700 dark:text-amber-400 mt-0.5">
                No verified Jan 1 balance found. The graph reconstructs it from imported transactions, but pinning a confirmed
                value makes the historical portion accurate even if some transactions weren't imported.
                {q1OpenBalance != null && (
                  <> Reconstructed estimate: <strong>{fmt(q1OpenBalance)}</strong>.</>
                )}
              </p>
              <div className="flex items-center gap-2 mt-3">
                <input
                  type="number"
                  step="0.01"
                  className="input py-1 w-36 text-sm"
                  placeholder={q1OpenBalance != null ? String(parseFloat(q1OpenBalance).toFixed(2)) : "Opening balance"}
                  value={yearStartValue}
                  onChange={e => setYearStartValue(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === "Enter" && yearStartValue) saveYearStartMut.mutate(parseFloat(yearStartValue));
                  }}
                />
                <button
                  onClick={() => saveYearStartMut.mutate(parseFloat(yearStartValue || (q1OpenBalance != null ? String(parseFloat(q1OpenBalance)) : "0")))}
                  disabled={saveYearStartMut.isPending || (!yearStartValue && q1OpenBalance == null)}
                  className="btn-primary text-xs px-3 py-1.5"
                >
                  {saveYearStartMut.isPending ? "Saving…" : "Set Jan 1 Balance"}
                </button>
                <button
                  onClick={() => { localStorage.setItem(yearStartDismissKey, "1"); setYearStartDismissed(true); }}
                  className="text-xs text-amber-500 hover:text-amber-700 underline"
                >
                  Dismiss
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {activeAccountId && (
        <RiskBanner
          risk={risk}
          accountId={activeAccountId}
          sourceAccounts={accounts.filter((a: any) => a.id !== activeAccountId).map((a: any) => ({ id: a.id, name: a.name }))}
          onAcceptSuggestion={(amount, targetDate, fromAccountId) =>
            acceptSuggestionMut.mutate({ to_account_id: activeAccountId, from_account_id: fromAccountId, amount, target_date: targetDate, suggested: true })
          }
        />
      )}
      <PlannedTransferReminder />

      {!isLoading && chartData.length > 0 && (
        <div className="card">
          <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
            <h3 className="font-semibold text-gray-900 dark:text-gray-100">
              {chartView === "balance"
                ? `Balance Over Time — ${year}${forecastYears > 1 ? `–${year + forecastYears - 1}` : ""}`
                : `Quarterly Net Income/Expense — ${year}${forecastYears > 1 ? `–${year + forecastYears - 1}` : ""}`}
            </h3>
            {chartView === "balance" && savingsAccounts.length > 0 && (
              <label className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400 cursor-pointer">
                <input type="checkbox" checked={showSavings} onChange={e => setShowSavings(e.target.checked)} />
                <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: "#0ea5e9", opacity: 0.45 }} />
                Savings ({savingsAccounts.map((a: any) => a.name).join(" + ")})
              </label>
            )}
          </div>
          <ResponsiveContainer width="100%" height={280}>
            {chartView === "net" ? (
              <BarChart data={netBarData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={chartTheme().grid} />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v: any, name: string) => [fmt(v), name]} />
                <ReferenceLine y={0} stroke="#ef4444" strokeDasharray="4 4" />
                <Bar dataKey="income" name="Income" fill={chartTheme().series2} />
                <Bar dataKey="expenses" name="Expenses" fill="#ef4444" />
                <Legend />
              </BarChart>
            ) : (
              <ComposedChart data={mergedData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
                <defs>
                  <linearGradient id="forecastActualGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#6366f1" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="#6366f1" stopOpacity={0.01} />
                  </linearGradient>
                  <linearGradient id="forecastProjectedGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#6366f1" stopOpacity={0.06} />
                    <stop offset="95%" stopColor="#6366f1" stopOpacity={0.00} />
                  </linearGradient>
                  <linearGradient id="forecastScenarioGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#10b981" stopOpacity={0.10} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0.01} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke={chartTheme().grid} />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
                <YAxis yAxisId="left" tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
                {/* Savings sits on its own axis on purpose. Sharing one would
                    flatten a $2k checking trough into invisibility against a
                    $30k savings balance -- the trough is the whole reason to
                    look at this chart. */}
                {hasSavingsSeries && (
                  <YAxis yAxisId="right" orientation="right" tickFormatter={v => `$${(v / 1000).toFixed(0)}k`}
                    tick={{ fontSize: 11, fill: "#94a3b8" }} axisLine={false} tickLine={false} />
                )}
                <Tooltip content={<CustomTooltip />} />
                <ReferenceLine yAxisId="left" y={0} stroke="#ef4444" strokeDasharray="4 4" strokeOpacity={0.5} />
                {lowBalanceThreshold != null && lowBalanceThreshold > 0 && (
                  <ReferenceLine
                    yAxisId="left"
                    y={lowBalanceThreshold}
                    stroke={isDarkMode() ? "#fbbf24" : "#b45309"}
                    strokeWidth={2}
                    strokeDasharray="6 3"
                    label={{ value: "Low balance threshold", position: "insideBottomRight", fontSize: 11, fontWeight: 600, fill: isDarkMode() ? "#fbbf24" : "#b45309" }}
                  />
                )}
                {risk?.action_threshold != null && (
                  <ReferenceLine
                    yAxisId="left"
                    y={parseFloat(risk.action_threshold)}
                    stroke={isDarkMode() ? "#f87171" : "#b91c1c"}
                    strokeWidth={2}
                    strokeDasharray="6 3"
                    label={{ value: "Action threshold", position: "insideTopRight", fontSize: 11, fontWeight: 600, fill: isDarkMode() ? "#f87171" : "#b91c1c" }}
                  />
                )}
                {hasSavingsSeries && (
                  <Bar yAxisId="right" dataKey="savings" name="Savings" fill="#0ea5e9" fillOpacity={0.30}
                    stroke="#0ea5e9" strokeOpacity={0.55} barSize={22} animationDuration={600} />
                )}
                <Area yAxisId="left" type="monotone" dataKey="actual" name="Actual" stroke={chartTheme().series} strokeWidth={2} fill="url(#forecastActualGradient)" dot={false} connectNulls={false} animationDuration={600} />
                <Area yAxisId="left" type="monotone" dataKey="projected" name="Projected" stroke={chartTheme().series} strokeWidth={2} strokeDasharray="5 3" fill="url(#forecastProjectedGradient)" dot={false} connectNulls={false} animationDuration={600} />
                {hasScenario && (
                  <Area yAxisId="left" type="monotone" dataKey="scenario" name="Scenario" stroke={chartTheme().series2} strokeWidth={2} fill="url(#forecastScenarioGradient)" dot={false} strokeDasharray="5 3" animationDuration={800} animationEasing="ease-out" />
                )}
                <Legend />
              </ComposedChart>
            )}
          </ResponsiveContainer>
        </div>
      )}

      {/* SS Tax Info */}
      {ssConfigured && ssLimitMonth && (
        <div className="card bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800">
          <div className="flex items-start gap-3">
            <TrendingUp size={18} className="text-green-600 mt-0.5 shrink-0" />
            <div>
              <p className="font-semibold text-green-800 dark:text-green-300 text-sm">Social Security Wage Base</p>
              <p className="text-sm text-green-700 dark:text-green-400 mt-1">
                Estimated SS limit reached: <strong>{ssLimitMonth}</strong>
                {ssPerPaycheckIncrease !== null && (
                  <> · Paycheck increases by ~<strong>{fmt(ssPerPaycheckIncrease)}</strong> after that</>
                )}
              </p>
              <p className="text-xs text-green-600 dark:text-green-500 mt-0.5">Based on ${ssGross?.toLocaleString()}/paycheck gross · from your actual forecast, not estimated</p>
            </div>
          </div>
        </div>
      )}

      {/* Credit Cards Due */}
      {(upcomingDue as any[]).length > 0 && (
        <div className="card">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-3 flex items-center gap-2">
            <CreditCard size={16} className="text-blue-500" /> Credit Cards Due
          </h3>
          <div className="divide-y divide-gray-100 dark:divide-gray-700">
            {(upcomingDue as any[]).map((entry: any) => (
              <div key={entry.card_id} className="py-3 flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{entry.card_name}</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    Due day {entry.due_day} · next{" "}
                    {new Date(entry.next_due_date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                  </p>
                </div>
                <div className="text-right">
                  <p className={`text-sm font-bold tabular-nums ${parseFloat(entry.balance_due) > 0 ? "text-red-600 dark:text-red-400" : "text-gray-400"}`}>
                    {parseFloat(entry.balance_due) > 0 ? fmt(entry.balance_due) : "—"}
                  </p>
                  <p className="text-xs text-gray-400">balance due</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Planned Expenses */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-semibold text-gray-900 dark:text-gray-100">Planned One-Offs</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">One-off future costs — or money coming in — that appear in the balance projection</p>
          </div>
          <button onClick={() => setShowExpenseForm(true)} className="btn-primary btn-sm text-xs px-3 py-1.5"><Plus size={14} /> Add</button>
        </div>

        {(plannedExpenses as any[]).length === 0 && !showExpenseForm && (
          <p className="text-sm text-gray-400 text-center py-4">No planned one-offs yet — add a vacation, a down payment, or an expected bonus</p>
        )}

        {(plannedExpenses as any[]).length > 0 && (
          <div className="divide-y divide-gray-100 dark:divide-gray-700 mb-4">
            {(plannedExpenses as any[]).map((pe: any) => (
              <div key={pe.id}>
                {editExpenseId === pe.id ? (
                  <div className="py-3 space-y-3">
                    <div className="grid grid-cols-2 gap-3">
                      <div className="col-span-2">
                        <label className="label">Name</label>
                        <input className="input" value={editExpenseForm.name} onChange={e => setEditExpenseForm({ ...editExpenseForm, name: e.target.value })} />
                      </div>
                      <div>
                        <label className="label">Amount</label>
                        <input type="number" step="0.01" className="input" value={editExpenseForm.amount} onChange={e => setEditExpenseForm({ ...editExpenseForm, amount: e.target.value })} />
                      </div>
                      <div>
                        <label className="label">Expected Date</label>
                        <input type="date" className="input" value={editExpenseForm.expected_date} onChange={e => setEditExpenseForm({ ...editExpenseForm, expected_date: e.target.value })} />
                      </div>
                      <div>
                        <label className="label">Direction</label>
                        <select className="input" value={editExpenseForm.direction} onChange={e => setEditExpenseForm({ ...editExpenseForm, direction: e.target.value })}>
                          <option value="outflow">Money out</option>
                          <option value="inflow">Money in</option>
                        </select>
                      </div>
                      <div>
                        {/* Encodes which of account_id/card_id this expense hits: "" = any
                            account, "account:<id>" = checking, "card:<id>" = card (paid off
                            later, on that card's next due date -- not on Expected Date). */}
                        <label className="label">Charge to</label>
                        <select
                          className="input"
                          value={editExpenseForm.card_id ? `card:${editExpenseForm.card_id}` : editExpenseForm.account_id ? `account:${editExpenseForm.account_id}` : ""}
                          onChange={e => {
                            const [kind, id] = e.target.value.split(":");
                            setEditExpenseForm({ ...editExpenseForm, account_id: kind === "account" ? id : "", card_id: kind === "card" ? id : "" });
                          }}
                        >
                          <option value="">Any checking account</option>
                          {checkingAccounts.map((a: any) => <option key={`a${a.id}`} value={`account:${a.id}`}>{a.name}</option>)}
                          {activeCards.map((c: any) => <option key={`c${c.id}`} value={`card:${c.id}`}>Card: {c.name}</option>)}
                        </select>
                      </div>
                        {/* A large purchase usually isn't paid from the month's cash flow.
                            Recording the source here keeps the transfer welded to the purchase
                            date, so moving one moves the other. */}
                        <div className="col-span-2">
                          <label className="label">Fund from (optional)</label>
                          <div className="flex flex-wrap items-center gap-2">
                            <select className="input flex-1 min-w-[10rem]" value={editExpenseForm.funding_account_id}
                              onChange={e => setEditExpenseForm({ ...editExpenseForm, funding_account_id: e.target.value })}>
                              <option value="">Paid from normal cash flow</option>
                              {fundingAccounts.map((a: any) => <option key={a.id} value={a.id}>{a.name}</option>)}
                            </select>
                            {editExpenseForm.funding_account_id && (
                              <>
                                <input type="number" step="0.01" className="input w-32" placeholder="Same as amount"
                                  value={editExpenseForm.funding_amount} onChange={e => setEditExpenseForm({ ...editExpenseForm, funding_amount: e.target.value })} />
                                <div className="flex items-center gap-1">
                                  <input type="number" className="input w-16" value={editExpenseForm.funding_lead_days}
                                    onChange={e => setEditExpenseForm({ ...editExpenseForm, funding_lead_days: e.target.value })} />
                                  <span className="text-xs text-gray-500 dark:text-gray-400">days before</span>
                                </div>
                              </>
                            )}
                          </div>
                          {editExpenseForm.funding_account_id && (
                            <p className="text-xs text-gray-400 mt-1">
                              Transfer moves with the purchase date. Blank amount moves exactly the purchase amount.
                            </p>
                          )}
                        </div>
                      <div className="col-span-2">
                        <label className="label">Notes (optional)</label>
                        <input className="input" value={editExpenseForm.notes} onChange={e => setEditExpenseForm({ ...editExpenseForm, notes: e.target.value })} />
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => updateExpenseMut.mutate({ id: pe.id, data: { name: editExpenseForm.name, amount: parseFloat(editExpenseForm.amount), expected_date: editExpenseForm.expected_date, notes: editExpenseForm.notes || null, account_id: editExpenseForm.account_id ? parseInt(editExpenseForm.account_id) : null, card_id: editExpenseForm.card_id ? parseInt(editExpenseForm.card_id) : null, direction: editExpenseForm.direction, funding_account_id: editExpenseForm.funding_account_id ? parseInt(editExpenseForm.funding_account_id) : null, funding_amount: editExpenseForm.funding_amount ? parseFloat(editExpenseForm.funding_amount) : null, funding_lead_days: editExpenseForm.funding_lead_days ? parseInt(editExpenseForm.funding_lead_days) : 0 } })}
                        disabled={!editExpenseForm.name || !editExpenseForm.amount || updateExpenseMut.isPending}
                        className="btn-primary text-sm"
                      >
                        {updateExpenseMut.isPending ? "Saving…" : "Save"}
                      </button>
                      <button onClick={() => setEditExpenseId(null)} className="btn-secondary text-sm">Cancel</button>
                    </div>
                  </div>
                ) : (
                  <div className="py-3">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                          {pe.name}
                          {pe.expected_date < todayStr && (
                            <span className="ml-2 text-[10px] uppercase tracking-wide text-amber-600 dark:text-amber-400">
                              date passed
                            </span>
                          )}
                        </p>
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                          {new Date(pe.expected_date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                          {pe.card_id && <> · via {activeCards.find((c: any) => c.id === pe.card_id)?.name ?? "card"}</>}
                          {pe.funding_account_id && (
                            <> · funded from {accounts.find((a: any) => a.id === pe.funding_account_id)?.name ?? "savings"}</>
                          )}
                          {pe.notes && <> · {pe.notes}</>}
                        </p>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className={`font-semibold ${pe.direction === "inflow" ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                          {pe.direction === "inflow" ? "+" : "−"}{fmt(pe.amount)}
                        </span>
                        <button onClick={() => { setEditExpenseId(pe.id); setEditExpenseForm({ name: pe.name, amount: String(pe.amount), expected_date: pe.expected_date, notes: pe.notes ?? "", account_id: pe.account_id ? String(pe.account_id) : "", card_id: pe.card_id ? String(pe.card_id) : "", direction: pe.direction ?? "outflow", funding_account_id: pe.funding_account_id ? String(pe.funding_account_id) : "", funding_amount: pe.funding_amount ? String(pe.funding_amount) : "", funding_lead_days: String(pe.funding_lead_days ?? 1) }); }} className="text-gray-300 hover:text-indigo-500"><Pencil size={14} /></button>
                        <button onClick={() => deleteExpenseMut.mutate(pe.id)} className="text-gray-300 hover:text-red-500"><Trash2 size={14} /></button>
                      </div>
                    </div>

                    {/* Once the date passes, the row stops being a plan and
                        becomes a question: did it happen, and for how much? */}
                    {pe.expected_date < todayStr && (
                      settleId === pe.id ? (
                        <div className="mt-2 flex flex-wrap items-center gap-2 bg-amber-50 dark:bg-amber-900/15 rounded-md px-3 py-2">
                          <span className="text-xs text-gray-600 dark:text-gray-300">Actual amount</span>
                          <input
                            type="number" step="0.01" autoFocus
                            className="input py-1 text-sm w-32"
                            placeholder={String(pe.amount)}
                            value={settleAmount}
                            onChange={e => setSettleAmount(e.target.value)}
                          />
                          <button
                            className="btn-primary text-xs px-2 py-1"
                            disabled={settleMut.isPending}
                            onClick={() => settleMut.mutate({ id: pe.id, actual: settleAmount ? parseFloat(settleAmount) : parseFloat(pe.amount) })}>
                            {settleMut.isPending ? "Saving…" : "Confirm"}
                          </button>
                          <button
                            className="btn-secondary text-xs px-2 py-1"
                            disabled={settleMut.isPending}
                            title="It never happened — close it out with no amount"
                            onClick={() => settleMut.mutate({ id: pe.id, actual: null })}>
                            Didn't happen
                          </button>
                          <button className="text-xs text-gray-400 hover:text-gray-600" onClick={() => { setSettleId(null); setSettleAmount(""); }}>Cancel</button>
                        </div>
                      ) : (
                        <button
                          className="mt-2 text-xs text-amber-700 dark:text-amber-400 hover:underline"
                          onClick={() => { setSettleId(pe.id); setSettleAmount(String(pe.amount)); }}>
                          Reconcile this →
                        </button>
                      )
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {showExpenseForm && (
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <div className="flex justify-between items-center mb-3">
              <p className="text-sm font-medium text-gray-900 dark:text-gray-100">New Planned One-Off</p>
              <button onClick={() => setShowExpenseForm(false)} className="text-gray-400 hover:text-gray-600"><X size={16} /></button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <label className="label">Name</label>
                <input className="input" placeholder="Vacation, down payment…" value={expenseForm.name} onChange={e => setExpenseForm({ ...expenseForm, name: e.target.value })} />
              </div>
              <div>
                <label className="label">Amount</label>
                <input type="number" step="0.01" className="input" placeholder="5000" value={expenseForm.amount} onChange={e => setExpenseForm({ ...expenseForm, amount: e.target.value })} />
              </div>
              <div>
                <label className="label">Expected Date</label>
                <input type="date" className="input" value={expenseForm.expected_date} onChange={e => setExpenseForm({ ...expenseForm, expected_date: e.target.value })} />
              </div>
              <div>
                <label className="label">Direction</label>
                <select className="input" value={expenseForm.direction} onChange={e => setExpenseForm({ ...expenseForm, direction: e.target.value })}>
                  <option value="outflow">Money out</option>
                  <option value="inflow">Money in</option>
                </select>
              </div>
              <div>
                <label className="label">Charge to</label>
                <select
                  className="input"
                  value={expenseForm.card_id ? `card:${expenseForm.card_id}` : expenseForm.account_id ? `account:${expenseForm.account_id}` : ""}
                  onChange={e => {
                    const [kind, id] = e.target.value.split(":");
                    setExpenseForm({ ...expenseForm, account_id: kind === "account" ? id : "", card_id: kind === "card" ? id : "" });
                  }}
                >
                  <option value="">Any checking account</option>
                  {checkingAccounts.map((a: any) => <option key={`a${a.id}`} value={`account:${a.id}`}>{a.name}</option>)}
                  {activeCards.map((c: any) => <option key={`c${c.id}`} value={`card:${c.id}`}>Card: {c.name}</option>)}
                </select>
                {expenseForm.card_id && (
                  <p className="text-xs text-gray-400 mt-1">Won't hit checking until this card's next statement is paid off.</p>
                )}
              </div>
                {/* A large purchase usually isn't paid from the month's cash flow.
                    Recording the source here keeps the transfer welded to the purchase
                    date, so moving one moves the other. */}
                <div className="col-span-2">
                  <label className="label">Fund from (optional)</label>
                  <div className="flex flex-wrap items-center gap-2">
                    <select className="input flex-1 min-w-[10rem]" value={expenseForm.funding_account_id}
                      onChange={e => setExpenseForm({ ...expenseForm, funding_account_id: e.target.value })}>
                      <option value="">Paid from normal cash flow</option>
                      {fundingAccounts.map((a: any) => <option key={a.id} value={a.id}>{a.name}</option>)}
                    </select>
                    {expenseForm.funding_account_id && (
                      <>
                        <input type="number" step="0.01" className="input w-32" placeholder="Same as amount"
                          value={expenseForm.funding_amount} onChange={e => setExpenseForm({ ...expenseForm, funding_amount: e.target.value })} />
                        <div className="flex items-center gap-1">
                          <input type="number" className="input w-16" value={expenseForm.funding_lead_days}
                            onChange={e => setExpenseForm({ ...expenseForm, funding_lead_days: e.target.value })} />
                          <span className="text-xs text-gray-500 dark:text-gray-400">days before</span>
                        </div>
                      </>
                    )}
                  </div>
                  {expenseForm.funding_account_id && (
                    <p className="text-xs text-gray-400 mt-1">
                      Transfer moves with the purchase date. Blank amount moves exactly the purchase amount.
                    </p>
                  )}
                </div>
              <div className="col-span-2">
                <label className="label">Notes (optional)</label>
                <input className="input" value={expenseForm.notes} onChange={e => setExpenseForm({ ...expenseForm, notes: e.target.value })} />
              </div>
              <div className="col-span-2 flex gap-2">
                <button
                  onClick={() => createExpenseMut.mutate({ name: expenseForm.name, amount: parseFloat(expenseForm.amount), expected_date: expenseForm.expected_date, notes: expenseForm.notes || null, account_id: expenseForm.account_id ? parseInt(expenseForm.account_id) : null, card_id: expenseForm.card_id ? parseInt(expenseForm.card_id) : null, direction: expenseForm.direction, funding_account_id: expenseForm.funding_account_id ? parseInt(expenseForm.funding_account_id) : null, funding_amount: expenseForm.funding_amount ? parseFloat(expenseForm.funding_amount) : null, funding_lead_days: expenseForm.funding_lead_days ? parseInt(expenseForm.funding_lead_days) : 0 })}
                  disabled={!expenseForm.name || !expenseForm.amount || createExpenseMut.isPending}
                  className="btn-primary"
                >
                  {createExpenseMut.isPending ? "Saving…" : "Add Planned Expense"}
                </button>
                <button onClick={() => setShowExpenseForm(false)} className="btn-secondary">Cancel</button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Quarter summaries */}
      <div className="space-y-3">
        {(quarters as any[]).map((q: any) => {
          const qKey = `${q.year}-${q.quarter}`;
          const qEndDate = quarterEndDates[q.quarter];
          const isPastQuarter = qEndDate < today_date;
          const forecastClose = parseFloat(q.close_balance);
          const savedBalance = q.quarter_end_checkpoint != null ? parseFloat(q.quarter_end_checkpoint) : undefined;
          const delta = savedBalance !== undefined ? savedBalance - forecastClose : null;
          const hasConflict = delta !== null && Math.abs(delta) > 1;
          // Last day of this quarter as YYYY-MM-DD for day checkpoint
          const qLastDay = (() => {
            const d = quarterEndDates[q.quarter];
            return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
          })();

          return (
          <div key={qKey} className="card">
            <button
              className="w-full flex items-center justify-between"
              onClick={() => setExpandedQ(expandedQ === q.quarter && forecastYears === 1 ? null : (expandedQ === q.quarter ? null : q.quarter))}
            >
              <div className="flex items-center gap-4">
                <span className="font-bold text-gray-900">Q{q.quarter} {q.year}</span>
                <span className={`text-sm font-semibold ${parseFloat(q.net) >= 0 ? "text-green-600" : "text-red-600"}`}>
                  {parseFloat(q.net) >= 0 ? "+" : ""}{fmt(q.net)} net
                </span>
              </div>
              <div className="flex items-center gap-6 text-sm text-gray-600">
                <span>Open: <strong className="text-gray-900">{fmt(q.open_balance)}</strong></span>
                <span>Close: {lowBalanceThreshold !== null && parseFloat(q.close_balance) < lowBalanceThreshold && <AlertTriangle size={12} className="inline mr-1 text-amber-500" />}<strong className={parseFloat(q.close_balance) >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600"}>{fmt(q.close_balance)}</strong></span>
                {expandedQ === q.quarter ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </div>
            </button>

            {/* Quarter-end balance anchor — uses unified day-checkpoint system */}
            {isPastQuarter && (
              <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-700 flex flex-wrap items-center gap-3">
                <span className="text-xs text-gray-500 dark:text-gray-400">Q{q.quarter} actual close:</span>
                {dayCheckpoint?.date === qLastDay ? (
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      step="0.01"
                      className="input py-1 w-32 text-sm"
                      value={dayCheckpoint.value}
                      onChange={e => setDayCheckpoint({ date: qLastDay, value: e.target.value })}
                      autoFocus
                      onKeyDown={e => {
                        if (e.key === "Enter" && dayCheckpoint.value)
                          saveDayCheckpointMut.mutate({ date: qLastDay, actual_balance: parseFloat(dayCheckpoint.value) });
                        if (e.key === "Escape") setDayCheckpoint(null);
                      }}
                    />
                    <button
                      onClick={() => saveDayCheckpointMut.mutate({ date: qLastDay, actual_balance: parseFloat(dayCheckpoint.value) })}
                      disabled={!dayCheckpoint.value || saveDayCheckpointMut.isPending}
                      className="btn-primary text-xs px-2 py-1"
                    >Save</button>
                    <button onClick={() => setDayCheckpoint(null)} className="btn-secondary text-xs px-2 py-1">Cancel</button>
                  </div>
                ) : (
                  <button
                    onClick={() => setDayCheckpoint({ date: qLastDay, value: savedBalance !== undefined ? String(savedBalance) : "" })}
                    className="text-xs text-indigo-500 hover:text-indigo-700 underline"
                  >
                    {savedBalance !== undefined ? fmt(savedBalance) : "Enter actual balance"}
                  </button>
                )}
                {hasConflict && (
                  <span className="flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
                    <AlertTriangle size={12} />
                    {delta! > 0 ? "+" : ""}{fmt(delta!)} vs forecast ·{" "}
                    <Link to="/transactions" className="underline hover:text-amber-700">Reconcile</Link>
                  </span>
                )}
              </div>
            )}

            {expandedQ === q.quarter && (
              <div className="mt-4 border-t border-gray-100 pt-4">
                <div className="grid grid-cols-2 gap-4 mb-4">
                  <div className="text-sm"><span className="text-gray-500">Total Income:</span> <strong className="text-green-600">{fmt(q.total_income)}</strong></div>
                  <div className="text-sm"><span className="text-gray-500">Total Expenses:</span> <strong className="text-red-600">{fmt(q.total_expenses)}</strong></div>
                </div>

                {/* Monthly accuracy panel — past months only */}
                {(() => {
                  const startMonth = (q.quarter - 1) * 3 + 1;
                  const monthsInQ = [startMonth, startMonth + 1, startMonth + 2];
                  const pastMonths = monthsInQ.filter(m => {
                    const lastDay = new Date(q.year, m, 0); // last day of month m
                    return lastDay < today_date;
                  });
                  if (pastMonths.length === 0) return null;
                  return (
                    <div className="mb-4 rounded-lg border border-gray-100 dark:border-gray-700 overflow-hidden">
                      <div className="px-3 py-2 bg-gray-50 dark:bg-gray-800/60 border-b border-gray-100 dark:border-gray-700">
                        <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">Monthly Forecast Accuracy</p>
                      </div>
                      <div className="px-3 divide-y divide-gray-100 dark:divide-gray-700">
                        {pastMonths.map(m => (
                          <MonthlyAccuracyRow key={m} accountId={activeAccountId} year={q.year} month={m} />
                        ))}
                      </div>
                    </div>
                  );
                })()}

                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-100">
                        <th className="text-left py-2 text-gray-500 font-medium">Date</th>
                        <th className="text-left py-2 text-gray-500 font-medium">Transactions</th>
                        <th className="text-right py-2 text-gray-500 font-medium">Balance</th>
                        <th className="w-16"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {q.days.filter((d: any) => d.transactions.length > 0 || dayCheckpointMap[d.date] !== undefined).map((d: any) => {
                        const hasCp = dayCheckpointMap[d.date] !== undefined;
                        return (
                        <tr key={d.date} className={`border-b border-gray-50 dark:border-gray-800 group hover:bg-gray-50 dark:hover:bg-gray-800/40 ${hasCp ? "bg-indigo-50/30 dark:bg-indigo-900/10" : ""}`}>
                          <td className="py-2 pr-4 text-gray-500 whitespace-nowrap">
                            {new Date(d.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                            {hasCp && <span className="ml-1 text-indigo-400" title="Balance checkpoint">⚓</span>}
                          </td>
                          <td className="py-2 pr-4">
                            {d.transactions.map((t: any, i: number) => (
                              <div key={i} className="flex items-center gap-2">
                                <span className={t.amount > 0 ? "text-green-600" : "text-red-600"}>
                                  {t.amount > 0 ? "+" : ""}{fmt(t.amount)}
                                </span>
                                <span className="text-gray-600">{t.name}</span>
                                {t.is_actual && <span className="px-1.5 py-0.5 rounded text-xs bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300">actual</span>}
                                {!t.is_actual && !t.is_planned && <span className="badge-blue">projected</span>}
                                {t.is_planned && <span className="px-1.5 py-0.5 rounded text-xs bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">planned</span>}
                                {t.is_transfer && <span className="px-1.5 py-0.5 rounded text-xs bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300">transfer</span>}
                              </div>
                            ))}
                            {hasCp && (
                              <div className="text-xs text-indigo-500 dark:text-indigo-300 mt-1">
                                Balance snapped to {fmt(dayCheckpointMap[d.date])}
                              </div>
                            )}
                            {/* Day checkpoint inline editor */}
                            {dayCheckpoint?.date === d.date ? (
                              <div className="flex items-center gap-1 mt-1">
                                <input
                                  type="number" step="0.01"
                                  className="input py-0.5 w-28 text-xs"
                                  placeholder="Actual balance"
                                  value={dayCheckpoint.value}
                                  autoFocus
                                  onChange={e => setDayCheckpoint({ date: d.date, value: e.target.value })}
                                  onKeyDown={e => {
                                    if (e.key === "Enter" && dayCheckpoint.value)
                                      saveDayCheckpointMut.mutate({ date: d.date, actual_balance: parseFloat(dayCheckpoint.value) });
                                    if (e.key === "Escape") setDayCheckpoint(null);
                                  }}
                                />
                                <button onClick={() => saveDayCheckpointMut.mutate({ date: d.date, actual_balance: parseFloat(dayCheckpoint.value) })}
                                  disabled={!dayCheckpoint.value || saveDayCheckpointMut.isPending}
                                  className="btn-primary text-xs px-2 py-0.5">Save</button>
                                {hasCp && (
                                  <button onClick={() => deleteDayCheckpointMut.mutate(d.date)}
                                    className="text-xs text-red-500 hover:text-red-700 px-1">Clear</button>
                                )}
                                <button onClick={() => setDayCheckpoint(null)} className="btn-secondary text-xs px-2 py-0.5">Cancel</button>
                              </div>
                            ) : null}
                          </td>
                          <td className="py-2 text-right font-semibold tabular-nums whitespace-nowrap">
                            {lowBalanceThreshold !== null && parseFloat(d.projected_balance) < lowBalanceThreshold && (
                              <AlertTriangle size={12} className="text-amber-500 inline mr-1" />
                            )}
                            {fmt(d.projected_balance)}
                          </td>
                          <td className="py-2 pl-2">
                            <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                              <button
                                title="Set actual balance for this date"
                                onClick={() => setDayCheckpoint({ date: d.date, value: hasCp ? String(dayCheckpointMap[d.date]) : "" })}
                                className="p-1 text-gray-400 hover:text-indigo-500 rounded"
                              >
                                <Pencil size={12} />
                              </button>
                              <button
                                title="Add transaction on this date"
                                onClick={() => { setAddTxnDate(d.date); setAddTxnForm({ description: "", amount: "", category_id: "" }); }}
                                className="p-1 text-gray-400 hover:text-green-500 rounded"
                              >
                                <Plus size={12} />
                              </button>
                            </div>
                          </td>
                        </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
          );
        })}
      </div>

      {isLoading && <div className="text-gray-400 text-sm text-center py-8">Building forecast…</div>}

      {/* Quick-add transaction modal */}
      {addTxnDate && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setAddTxnDate(null)}>
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl p-6 w-full max-w-sm space-y-4" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-gray-900 dark:text-gray-100">
                Add Transaction — {new Date(addTxnDate + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
              </h3>
              <button onClick={() => setAddTxnDate(null)} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="label">Description</label>
                <input className="input w-full" placeholder="e.g. Dentist copay" autoFocus
                  value={addTxnForm.description}
                  onChange={e => setAddTxnForm(f => ({ ...f, description: e.target.value }))} />
              </div>
              <div>
                <label className="label">Amount (negative = expense)</label>
                <input className="input w-full" type="number" step="0.01" placeholder="-150.00"
                  value={addTxnForm.amount}
                  onChange={e => setAddTxnForm(f => ({ ...f, amount: e.target.value }))} />
              </div>
              <div>
                <label className="label">Category (optional)</label>
                <select className="input w-full" value={addTxnForm.category_id}
                  onChange={e => setAddTxnForm(f => ({ ...f, category_id: e.target.value }))}>
                  <option value="">No category</option>
                  {allCatOptions.map((c: any) => (
                    <option key={c.id} value={c.id}>{c.parent_id ? "  " : ""}{c.name}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex gap-2 justify-end">
              <button onClick={() => setAddTxnDate(null)} className="btn-secondary">Cancel</button>
              <button
                disabled={!addTxnForm.description || !addTxnForm.amount || createTxnMut.isPending}
                onClick={() => createTxnMut.mutate({
                  date: addTxnDate,
                  description: addTxnForm.description,
                  amount: parseFloat(addTxnForm.amount),
                  category_id: addTxnForm.category_id ? parseInt(addTxnForm.category_id) : null,
                  account_id: activeAccountId,
                  is_actual: true,
                })}
                className="btn-primary"
              >
                {createTxnMut.isPending ? "Saving…" : "Add Transaction"}
              </button>
            </div>
          </div>
        </div>
      )}

      {showHelp && <HelpPanel title="Forecast" body={"Day-by-day cash flow projection based on your recurring income and bills.\n\nSelect an account and year to see the balance line. Q1–Q4 summaries show open/close balances and net cash flow.\n\nScenarios let you model 'what if I cut dining by $200/month?' with a second line chart trace.\n\nPlanned Expenses are one-off future costs (vacation, down payment) injected into the forecast balance.\n\nWeekend bills are automatically shifted to the preceding Friday."} onClose={() => setShowHelp(false)} />}
    </div>
  );
}

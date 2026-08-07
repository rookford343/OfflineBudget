import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { accountsApi, forecastApi, scenariosApi, plannedExpensesApi, authApi, cardsApi, dayCheckpointsApi, transactionsApi, categoriesApi } from "../api";
import { fmt, today } from "../lib/utils";
import { Link } from "react-router-dom";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Legend, BarChart, Bar } from "recharts";
import { ChevronDown, ChevronUp, AlertTriangle, Plus, Trash2, X, TrendingUp, HelpCircle, CreditCard, Pencil, ShieldCheck } from "lucide-react";
import HelpPanel from "../components/HelpPanel";
import MonthlyAccuracyRow from "../components/MonthlyAccuracyRow";
import { RiskBanner } from "../components/RiskBanner";

function isDarkMode(): boolean {
  return document.documentElement.classList.contains("dark");
}

function chartTheme() {
  const dark = isDarkMode();
  return {
    grid:    dark ? "#2c3040" : "#e5e7eb",
    tick:    dark ? "#6e7888" : "#6b7280",
    tooltip: dark ? "#1f2330" : "#ffffff",
    tooltipBorder: dark ? "#2c3040" : "#e5e7eb",
    tooltipText: dark ? "#c4ccd8" : "#111827",
  };
}

const emptyExpense = { name: "", amount: "", expected_date: today(), notes: "", account_id: "" };

export default function Forecast() {
  const qc = useQueryClient();
  const { data: accounts = [] } = useQuery({ queryKey: ["accounts"], queryFn: accountsApi.list });
  const checkingAccounts = accounts.filter((a: any) => a.type === "checking");
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

  const { data: scenarios = [] } = useQuery({
    queryKey: ["scenarios"],
    queryFn: scenariosApi.list,
  });

  const { data: plannedExpenses = [] } = useQuery({
    queryKey: ["planned-expenses"],
    queryFn: plannedExpensesApi.list,
  });

  const { data: me } = useQuery({
    queryKey: ["me"],
    queryFn: authApi.me,
  });

  const { data: upcomingDue = [] } = useQuery<any[]>({
    queryKey: ["cards-upcoming-due"],
    queryFn: cardsApi.upcomingDue,
  });

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

  const allCatOptions = (categories as any[]).flatMap((c: any) => [c, ...(c.children ?? [])]);

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
  const chartData = (quarters as any[]).flatMap((q: any) =>
    q.days.filter((_: any, i: number) => i % 3 === 0).map((d: any) => {
      const balance = parseFloat(d.projected_balance);
      return {
        date: d.date,
        baseline: balance,
        actual: d.date <= todayStr ? balance : null,
        projected: d.date >= todayStr ? balance : null,
        label: new Date(d.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }),
      };
    })
  );

  // Merge scenario trace into chart data
  const scenarioMap: Record<string, number> = {};
  if (scenarioId !== null && (scenarioQuarters as any[]).length > 0) {
    (scenarioQuarters as any[]).forEach((q: any) =>
      q.days.filter((_: any, i: number) => i % 3 === 0).forEach((d: any) => {
        scenarioMap[d.date] = parseFloat(d.projected_balance);
      })
    );
  }

  const mergedData = chartData.map(d => ({
    ...d,
    scenario: scenarioMap[d.date] ?? undefined,
  }));

  const hasScenario = scenarioId !== null && Object.keys(scenarioMap).length > 0;

  // Net view: one bar per quarter
  const netBarData = (quarters as any[]).map((q: any) => ({
    name: forecastYears > 1 ? `Q${q.quarter} ${q.year}` : `Q${q.quarter}`,
    net: parseFloat(q.net),
    income: parseFloat(q.total_income),
    expenses: parseFloat(q.total_expenses),
  }));

  // SS limit estimate
  const ssGross = me?.ss_gross_per_paycheck ? parseFloat(me.ss_gross_per_paycheck) : null;
  const ssWageBase = me?.ss_wage_base ? parseFloat(me.ss_wage_base) : 176100;
  const ssBonus = me?.ss_bonus_ytd ? parseFloat(me.ss_bonus_ytd) : 0;
  const ssConfigured = ssGross !== null && ssGross > 0;
  let ssLimitMonth: string | null = null;
  let ssPerPaycheckIncrease: number | null = null;
  if (ssConfigured) {
    const remainingWageBase = ssWageBase - ssBonus;
    const payPeriodsToLimit = Math.ceil(remainingWageBase / ssGross!);
    const ssDate = new Date(year, 0, 1);
    ssDate.setDate(ssDate.getDate() + (payPeriodsToLimit - 1) * 14);
    ssLimitMonth = ssDate.toLocaleDateString("en-US", { month: "long", year: "numeric" });
    ssPerPaycheckIncrease = ssGross! * 0.062;
  }

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload?.length) {
      const nameMap: Record<string, string> = { actual: "Actual", projected: "Projected", scenario: "Scenario", baseline: "Balance" };
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
              <p className="text-xs text-indigo-700 dark:text-indigo-400 mt-0.5">
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

      {activeAccountId && <RiskBanner risk={risk} />}

      {!isLoading && chartData.length > 0 && (
        <div className="card">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-4">
            {chartView === "balance"
              ? `Balance Over Time — ${year}${forecastYears > 1 ? `–${year + forecastYears - 1}` : ""}`
              : `Quarterly Net Income/Expense — ${year}${forecastYears > 1 ? `–${year + forecastYears - 1}` : ""}`}
          </h3>
          <ResponsiveContainer width="100%" height={280}>
            {chartView === "net" ? (
              <BarChart data={netBarData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={chartTheme().grid} />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v: any, name: string) => [fmt(v), name]} />
                <ReferenceLine y={0} stroke="#ef4444" strokeDasharray="4 4" />
                <Bar dataKey="income" name="Income" fill="#10b981" />
                <Bar dataKey="expenses" name="Expenses" fill="#ef4444" />
                <Legend />
              </BarChart>
            ) : (
              <AreaChart data={mergedData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
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
                <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
                <Tooltip content={<CustomTooltip />} />
                <ReferenceLine y={0} stroke="#ef4444" strokeDasharray="4 4" />
                {lowBalanceThreshold != null && lowBalanceThreshold > 0 && (
                  <ReferenceLine y={lowBalanceThreshold} stroke="#f59e0b" strokeDasharray="4 4" label={{ value: "Low balance threshold", fontSize: 10, fill: "#f59e0b" }} />
                )}
                {risk?.action_threshold != null && (
                  <ReferenceLine y={parseFloat(risk.action_threshold)} stroke="#dc2626" strokeDasharray="4 4" label={{ value: "Action threshold", fontSize: 10, fill: "#dc2626" }} />
                )}
                <Area type="monotone" dataKey="actual" name="Actual" stroke="#6366f1" strokeWidth={2} fill="url(#forecastActualGradient)" dot={false} connectNulls={false} animationDuration={600} />
                <Area type="monotone" dataKey="projected" name="Projected" stroke="#6366f1" strokeWidth={2} strokeDasharray="5 3" fill="url(#forecastProjectedGradient)" dot={false} connectNulls={false} animationDuration={600} />
                {hasScenario && (
                  <Area type="monotone" dataKey="scenario" name="Scenario" stroke="#10b981" strokeWidth={2} fill="url(#forecastScenarioGradient)" dot={false} strokeDasharray="5 3" animationDuration={800} animationEasing="ease-out" />
                )}
                <Legend />
              </AreaChart>
            )}
          </ResponsiveContainer>
        </div>
      )}

      {/* SS Tax Info */}
      {ssConfigured && (
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
              <p className="text-xs text-green-600 dark:text-green-500 mt-0.5">Based on ${ssGross?.toLocaleString()}/paycheck gross · ${ssWageBase.toLocaleString()} wage base</p>
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
            <h3 className="font-semibold text-gray-900 dark:text-gray-100">Planned Expenses</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">One-off future costs that appear in the balance projection</p>
          </div>
          <button onClick={() => setShowExpenseForm(true)} className="btn-primary btn-sm text-xs px-3 py-1.5"><Plus size={14} /> Add</button>
        </div>

        {(plannedExpenses as any[]).length === 0 && !showExpenseForm && (
          <p className="text-sm text-gray-400 text-center py-4">No planned expenses yet — add a vacation, down payment, or other future cost</p>
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
                        <label className="label">Account (optional)</label>
                        <select className="input" value={editExpenseForm.account_id} onChange={e => setEditExpenseForm({ ...editExpenseForm, account_id: e.target.value })}>
                          <option value="">Any account</option>
                          {checkingAccounts.map((a: any) => <option key={a.id} value={a.id}>{a.name}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="label">Notes (optional)</label>
                        <input className="input" value={editExpenseForm.notes} onChange={e => setEditExpenseForm({ ...editExpenseForm, notes: e.target.value })} />
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => updateExpenseMut.mutate({ id: pe.id, data: { name: editExpenseForm.name, amount: parseFloat(editExpenseForm.amount), expected_date: editExpenseForm.expected_date, notes: editExpenseForm.notes || null, account_id: editExpenseForm.account_id ? parseInt(editExpenseForm.account_id) : null } })}
                        disabled={!editExpenseForm.name || !editExpenseForm.amount || updateExpenseMut.isPending}
                        className="btn-primary text-sm"
                      >
                        {updateExpenseMut.isPending ? "Saving…" : "Save"}
                      </button>
                      <button onClick={() => setEditExpenseId(null)} className="btn-secondary text-sm">Cancel</button>
                    </div>
                  </div>
                ) : (
                  <div className="py-3 flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{pe.name}</p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        {new Date(pe.expected_date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                        {pe.notes && <> · {pe.notes}</>}
                      </p>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="font-semibold text-red-600">{fmt(pe.amount)}</span>
                      <button onClick={() => { setEditExpenseId(pe.id); setEditExpenseForm({ name: pe.name, amount: String(pe.amount), expected_date: pe.expected_date, notes: pe.notes ?? "", account_id: pe.account_id ? String(pe.account_id) : "" }); }} className="text-gray-300 hover:text-indigo-500"><Pencil size={14} /></button>
                      <button onClick={() => deleteExpenseMut.mutate(pe.id)} className="text-gray-300 hover:text-red-500"><Trash2 size={14} /></button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {showExpenseForm && (
          <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
            <div className="flex justify-between items-center mb-3">
              <p className="text-sm font-medium text-gray-900 dark:text-gray-100">New Planned Expense</p>
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
                <label className="label">Account (optional)</label>
                <select className="input" value={expenseForm.account_id} onChange={e => setExpenseForm({ ...expenseForm, account_id: e.target.value })}>
                  <option value="">Any account</option>
                  {checkingAccounts.map((a: any) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              </div>
              <div>
                <label className="label">Notes (optional)</label>
                <input className="input" value={expenseForm.notes} onChange={e => setExpenseForm({ ...expenseForm, notes: e.target.value })} />
              </div>
              <div className="col-span-2 flex gap-2">
                <button
                  onClick={() => createExpenseMut.mutate({ name: expenseForm.name, amount: parseFloat(expenseForm.amount), expected_date: expenseForm.expected_date, notes: expenseForm.notes || null, account_id: expenseForm.account_id ? parseInt(expenseForm.account_id) : null })}
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
                              <div className="text-xs text-indigo-500 dark:text-indigo-400 mt-1">
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

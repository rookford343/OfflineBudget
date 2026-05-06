import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { accountsApi, forecastApi, scenariosApi, plannedExpensesApi, authApi, cardsApi, checkpointsApi } from "../api";
import { fmt, today } from "../lib/utils";
import { Link } from "react-router-dom";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Legend } from "recharts";
import { ChevronDown, ChevronUp, AlertTriangle, Plus, Trash2, X, TrendingUp, HelpCircle, CreditCard, Pencil } from "lucide-react";
import HelpPanel from "../components/HelpPanel";

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
  const [expandedQ, setExpandedQ] = useState<number | null>(null);
  const [scenarioId, setScenarioId] = useState<number | null>(null);
  const [showHelp, setShowHelp] = useState(false);
  const [showExpenseForm, setShowExpenseForm] = useState(false);
  const [expenseForm, setExpenseForm] = useState({ ...emptyExpense });
  const [editExpenseId, setEditExpenseId] = useState<number | null>(null);
  const [editExpenseForm, setEditExpenseForm] = useState({ ...emptyExpense });

  const activeAccountId = accountId ?? checkingAccounts[0]?.id;
  const activeAccount = checkingAccounts.find((a: any) => a.id === activeAccountId);
  const lowBalanceThreshold = activeAccount?.low_balance_threshold != null
    ? parseFloat(activeAccount.low_balance_threshold)
    : null;

  const { data: quarters = [], isLoading } = useQuery({
    queryKey: ["forecast-quarters", activeAccountId, year],
    queryFn: () => forecastApi.quarters(activeAccountId, year),
    enabled: !!activeAccountId,
  });

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

  const { data: checkpoints = [] } = useQuery<any[]>({
    queryKey: ["checkpoints", activeAccountId],
    queryFn: () => checkpointsApi.list(activeAccountId!),
    enabled: !!activeAccountId,
  });

  const [checkpoint, setCheckpoint] = useState<{ key: string; value: string } | null>(null);

  const saveCheckpointMut = useMutation({
    mutationFn: ({ year, quarter, actual_balance }: { year: number; quarter: number; actual_balance: number }) =>
      checkpointsApi.upsert(year, quarter, activeAccountId!, actual_balance),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["checkpoints"] });
      setCheckpoint(null);
    },
  });

  const checkpointMap: Record<string, number> = {};
  (checkpoints as any[]).forEach((c: any) => {
    checkpointMap[`${c.year}-${c.quarter}`] = parseFloat(c.actual_balance);
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

  // Baseline chart data
  const chartData = (quarters as any[]).flatMap((q: any) =>
    q.days.filter((_: any, i: number) => i % 3 === 0).map((d: any) => ({
      date: d.date,
      baseline: parseFloat(d.projected_balance),
      label: new Date(d.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }),
    }))
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
      return (
        <div className="card py-2 px-3 shadow-lg text-sm">
          <p className="text-gray-500 text-xs mb-1">{label}</p>
          {payload.map((p: any) => (
            <p key={p.dataKey} className="font-bold" style={{ color: p.color }}>
              {p.dataKey === "baseline" ? "Baseline" : "Scenario"}: {fmt(p.value)}
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
        <div className="flex gap-2 flex-wrap">
          <select className="input w-auto" value={activeAccountId ?? ""} onChange={e => setAccountId(parseInt(e.target.value))}>
            {checkingAccounts.map((a: any) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <select className="input w-auto" value={year} onChange={e => setYear(parseInt(e.target.value))}>
            {[-1, 0, 1, 2].map(d => <option key={d} value={new Date().getFullYear() + d}>{new Date().getFullYear() + d}</option>)}
          </select>
          <select className="input w-auto" value={scenarioId ?? ""} onChange={e => setScenarioId(e.target.value === "" ? null : parseInt(e.target.value))}>
            <option value="">Baseline only</option>
            {(scenarios as any[]).map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </div>
      </div>

      {checkingAccounts.length === 0 && (
        <div className="card text-center py-8 text-gray-400">Add a checking account to see your forecast.</div>
      )}

      {!isLoading && chartData.length > 0 && (
        <div className="card">
          <h3 className="font-semibold text-gray-900 mb-4">Balance Over Time — {year}</h3>
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={mergedData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
              <defs>
                <linearGradient id="forecastBaselineGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#6366f1" stopOpacity={0.12} />
                  <stop offset="95%" stopColor="#6366f1" stopOpacity={0.01} />
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
              <Area type="monotone" dataKey="baseline" name="Baseline" stroke="#6366f1" strokeWidth={2} fill="url(#forecastBaselineGradient)" dot={false} animationDuration={800} animationEasing="ease-out" />
              {hasScenario && (
                <Area type="monotone" dataKey="scenario" name="Scenario" stroke="#10b981" strokeWidth={2} fill="url(#forecastScenarioGradient)" dot={false} strokeDasharray="5 3" animationDuration={800} animationEasing="ease-out" />
              )}
              {hasScenario && <Legend />}
            </AreaChart>
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
          const savedBalance = checkpointMap[qKey];
          const forecastClose = parseFloat(q.close_balance);
          const delta = savedBalance !== undefined ? savedBalance - forecastClose : null;
          const hasConflict = delta !== null && Math.abs(delta) > 1;

          return (
          <div key={q.quarter} className="card">
            <button
              className="w-full flex items-center justify-between"
              onClick={() => setExpandedQ(expandedQ === q.quarter ? null : q.quarter)}
            >
              <div className="flex items-center gap-4">
                <span className="font-bold text-gray-900">Q{q.quarter} {q.year}</span>
                <span className={`text-sm font-semibold ${parseFloat(q.net) >= 0 ? "text-green-600" : "text-red-600"}`}>
                  {parseFloat(q.net) >= 0 ? "+" : ""}{fmt(q.net)} net
                </span>
              </div>
              <div className="flex items-center gap-6 text-sm text-gray-600">
                <span>Open: <strong className="text-gray-900">{fmt(q.open_balance)}</strong></span>
                <span>Close: <strong className={parseFloat(q.close_balance) >= 0 ? "text-gray-900" : "text-red-600"}>{fmt(q.close_balance)}</strong></span>
                {expandedQ === q.quarter ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </div>
            </button>

            {/* Quarterly checkpoint for past quarters */}
            {isPastQuarter && (
              <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-700 flex flex-wrap items-center gap-3">
                <span className="text-xs text-gray-500 dark:text-gray-400">Q{q.quarter} actual close:</span>
                {checkpoint?.key === qKey ? (
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      step="0.01"
                      className="input py-1 w-32 text-sm"
                      value={checkpoint.value}
                      onChange={e => setCheckpoint({ key: qKey, value: e.target.value })}
                      autoFocus
                      onKeyDown={e => {
                        if (e.key === "Enter") saveCheckpointMut.mutate({ year: q.year, quarter: q.quarter, actual_balance: parseFloat(checkpoint.value) });
                        if (e.key === "Escape") setCheckpoint(null);
                      }}
                    />
                    <button
                      onClick={() => saveCheckpointMut.mutate({ year: q.year, quarter: q.quarter, actual_balance: parseFloat(checkpoint.value) })}
                      disabled={!checkpoint.value || saveCheckpointMut.isPending}
                      className="btn-primary text-xs px-2 py-1"
                    >Save</button>
                    <button onClick={() => setCheckpoint(null)} className="btn-secondary text-xs px-2 py-1">Cancel</button>
                  </div>
                ) : (
                  <button
                    onClick={() => setCheckpoint({ key: qKey, value: savedBalance !== undefined ? String(savedBalance) : "" })}
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
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-100">
                        <th className="text-left py-2 text-gray-500 font-medium">Date</th>
                        <th className="text-left py-2 text-gray-500 font-medium">Transactions</th>
                        <th className="text-right py-2 text-gray-500 font-medium">Balance</th>
                      </tr>
                    </thead>
                    <tbody>
                      {q.days.filter((d: any) => d.transactions.length > 0).map((d: any) => (
                        <tr key={d.date} className="border-b border-gray-50 hover:bg-gray-50">
                          <td className="py-2 pr-4 text-gray-500 whitespace-nowrap">
                            {new Date(d.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                          </td>
                          <td className="py-2 pr-4">
                            {d.transactions.map((t: any, i: number) => (
                              <div key={i} className="flex items-center gap-2">
                                <span className={t.amount > 0 ? "text-green-600" : "text-red-600"}>
                                  {t.amount > 0 ? "+" : ""}{fmt(t.amount)}
                                </span>
                                <span className="text-gray-600">{t.name}</span>
                                {!t.is_actual && !t.is_planned && <span className="badge-blue">projected</span>}
                                {t.is_planned && <span className="px-1.5 py-0.5 rounded text-xs bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">planned</span>}
                              </div>
                            ))}
                          </td>
                          <td className="py-2 text-right font-semibold tabular-nums whitespace-nowrap">
                            {lowBalanceThreshold !== null && parseFloat(d.projected_balance) < lowBalanceThreshold && (
                              <AlertTriangle size={12} className="text-amber-500 inline mr-1" />
                            )}
                            {fmt(d.projected_balance)}
                          </td>
                        </tr>
                      ))}
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
      {showHelp && <HelpPanel title="Forecast" body={"Day-by-day cash flow projection based on your recurring income and bills.\n\nSelect an account and year to see the balance line. Q1–Q4 summaries show open/close balances and net cash flow.\n\nScenarios let you model 'what if I cut dining by $200/month?' with a second line chart trace.\n\nPlanned Expenses are one-off future costs (vacation, down payment) injected into the forecast balance.\n\nWeekend bills are automatically shifted to the preceding Friday."} onClose={() => setShowHelp(false)} />}
    </div>
  );
}

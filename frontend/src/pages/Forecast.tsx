import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { accountsApi, forecastApi, scenariosApi } from "../api";
import { fmt } from "../lib/utils";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Legend } from "recharts";
import { ChevronDown, ChevronUp, AlertTriangle } from "lucide-react";

export default function Forecast() {
  const { data: accounts = [] } = useQuery({ queryKey: ["accounts"], queryFn: accountsApi.list });
  const checkingAccounts = accounts.filter((a: any) => a.type === "checking");
  const [accountId, setAccountId] = useState<number | null>(null);
  const [year, setYear] = useState(new Date().getFullYear());
  const [expandedQ, setExpandedQ] = useState<number | null>(null);
  const [scenarioId, setScenarioId] = useState<number | null>(null);

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
          <h2 className="text-xl font-bold text-gray-900">Forecast</h2>
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
            <LineChart data={mergedData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
              <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
              <Tooltip content={<CustomTooltip />} />
              <ReferenceLine y={0} stroke="#ef4444" strokeDasharray="4 4" />
              <Line type="monotone" dataKey="baseline" name="Baseline" stroke="#6366f1" strokeWidth={2} dot={false} />
              {hasScenario && (
                <Line type="monotone" dataKey="scenario" name="Scenario" stroke="#10b981" strokeWidth={2} dot={false} strokeDasharray="5 3" />
              )}
              {hasScenario && <Legend />}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Quarter summaries */}
      <div className="space-y-3">
        {(quarters as any[]).map((q: any) => (
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
                                {!t.is_actual && <span className="badge-blue">projected</span>}
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
        ))}
      </div>

      {isLoading && <div className="text-gray-400 text-sm text-center py-8">Building forecast…</div>}
    </div>
  );
}

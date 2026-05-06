import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { budgetApi } from "../api";
import { fmt } from "../lib/utils";
import { Pencil, Check, X, RotateCcw, HelpCircle } from "lucide-react";
import HelpPanel from "../components/HelpPanel";

export default function Budget() {
  const now = new Date();
  const [showHelp, setShowHelp] = useState(false);
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [editId, setEditId] = useState<number | null>(null);
  const [editAmt, setEditAmt] = useState("");
  const qc = useQueryClient();

  const { data: overview = [], isLoading } = useQuery<any[]>({
    queryKey: ["budget-overview", year, month],
    queryFn: () => budgetApi.overview(year, month),
  });

  const upsertMut = useMutation({
    mutationFn: budgetApi.upsert,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["budget-overview"] }); setEditId(null); },
  });

  const rolloverToggleMut = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      budgetApi.setCategoryRollover(id, enabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["budget-overview"] }),
  });

  const applyRolloverMut = useMutation({
    mutationFn: () => {
      const prevMonth = month === 1 ? 12 : month - 1;
      const prevYear = month === 1 ? year - 1 : year;
      return budgetApi.applyRollover(prevYear, prevMonth);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["budget-overview"] }),
  });

  function saveEdit(catId: number) {
    upsertMut.mutate({ category_id: catId, year, month: 0, budgeted_amount: parseFloat(editAmt) });
  }

  const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  const tops = overview.filter((r: any) => !r.parent_id);
  const subs = overview.filter((r: any) => r.parent_id);
  const subsByParent: Record<number, any[]> = {};
  subs.forEach((s: any) => { (subsByParent[s.parent_id] ??= []).push(s); });

  function rowStatusClass(available: number, pctUsed: number): string {
    if (available === 0) return "budget-row-unset";
    if (pctUsed >= 100) return "budget-row-over";
    if (pctUsed >= 80) return "budget-row-warn";
    return "budget-row-ok";
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-1.5">Budget <button onClick={() => setShowHelp(true)} className="text-gray-400 hover:text-indigo-500 font-normal"><HelpCircle size={15} /></button></h2>
          <p className="text-sm text-gray-500 dark:text-gray-400">Set monthly targets and track actual spending</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => applyRolloverMut.mutate()}
            disabled={applyRolloverMut.isPending}
            className="btn-secondary flex items-center gap-1.5 text-sm"
            title="Carry unspent budget from last month forward into rollover-enabled categories"
          >
            <RotateCcw size={14} className={applyRolloverMut.isPending ? "animate-spin" : ""} />
            Apply Last Month's Rollover
          </button>
          <select className="input w-auto" value={month} onChange={e => setMonth(parseInt(e.target.value))}>
            {monthNames.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
          </select>
          <select className="input w-auto" value={year} onChange={e => setYear(parseInt(e.target.value))}>
            {[-1, 0, 1].map(d => <option key={d} value={now.getFullYear() + d}>{now.getFullYear() + d}</option>)}
          </select>
        </div>
      </div>

      <div className="card overflow-hidden p-0">
        {isLoading && <p className="text-sm text-gray-400 text-center py-8">Loading…</p>}
        {!isLoading && (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-800 border-b border-gray-100 dark:border-gray-700">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Category</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Budget</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Rollover</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Available</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Checking</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Cards</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Total</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Left</th>
                <th className="px-4 py-3 w-10"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
              {tops.map((row: any) => {
                const rolloverBalance = parseFloat(row.rollover_balance || "0");
                const budgeted = parseFloat(row.budgeted || "0");
                const available = row.rollover_enabled ? budgeted + rolloverBalance : budgeted;
                const actualTotal = parseFloat(row.actual_total || "0");
                const left = available - actualTotal;
                const pctUsed = available > 0 ? (actualTotal / available) * 100 : 0;
                const statusClass = rowStatusClass(available, pctUsed);
                return (
                  <React.Fragment key={row.category_id}>
                    <tr className={`bg-gray-50/60 dark:bg-gray-800/40 ${statusClass}`}>
                      <td className="px-4 py-2.5 font-semibold text-gray-900 dark:text-white">
                        <div className="flex items-center gap-2">
                          {row.category_name}
                          <label className="flex items-center gap-1 cursor-pointer" title="Enable rollover for this category">
                            <input
                              type="checkbox"
                              checked={!!row.rollover_enabled}
                              onChange={e => rolloverToggleMut.mutate({ id: row.category_id, enabled: e.target.checked })}
                              className="w-3 h-3 accent-indigo-500"
                            />
                            <span className="text-xs font-normal text-gray-400">rollover</span>
                          </label>
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        {editId === row.category_id ? (
                          <div className="flex items-center justify-end gap-1">
                            <input type="number" step="0.01" className="input w-24 py-1 text-right" value={editAmt} onChange={e => setEditAmt(e.target.value)} autoFocus />
                            <button onClick={() => saveEdit(row.category_id)} className="text-green-600 hover:text-green-700"><Check size={14} /></button>
                            <button onClick={() => setEditId(null)} className="text-gray-400 hover:text-gray-600"><X size={14} /></button>
                          </div>
                        ) : (
                          <span className="text-blue-600 font-medium">{budgeted > 0 ? fmt(budgeted) : "—"}</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        {row.rollover_enabled && rolloverBalance > 0 ? (
                          <span className="text-amber-600 dark:text-amber-400 font-medium text-xs">+{fmt(rolloverBalance)}</span>
                        ) : (
                          <span className="text-gray-300 dark:text-gray-600">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        {budgeted > 0 || (row.rollover_enabled && rolloverBalance > 0) ? (
                          <span className="font-medium text-gray-900 dark:text-white">{fmt(available)}</span>
                        ) : (
                          <span className="text-gray-300 dark:text-gray-600">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right text-gray-600 dark:text-gray-400">{fmt(row.actual_checking)}</td>
                      <td className="px-4 py-2.5 text-right text-gray-600 dark:text-gray-400">{fmt(row.actual_cards)}</td>
                      <td className="px-4 py-2.5 text-right font-semibold text-gray-900 dark:text-white">{fmt(row.actual_total)}</td>
                      <td className={`px-4 py-2.5 text-right font-semibold ${left < 0 ? "text-red-600 dark:text-red-400" : "text-green-600 dark:text-green-400"}`}>
                        {budgeted > 0 || (row.rollover_enabled && rolloverBalance > 0) ? (
                          <div>
                            <div>{fmt(left)}</div>
                            <div className="mt-1 h-1 w-12 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden ml-auto">
                              <div
                                className={`h-full rounded-full ${pctUsed >= 100 ? "bg-red-500" : pctUsed >= 80 ? "bg-amber-500" : "bg-green-500"}`}
                                style={{ width: `${Math.min(100, pctUsed)}%` }}
                              />
                            </div>
                          </div>
                        ) : "—"}
                      </td>
                      <td className="px-4 py-2.5">
                        <button onClick={() => { setEditId(row.category_id); setEditAmt(row.budgeted); }} className="text-gray-300 hover:text-indigo-500"><Pencil size={13} /></button>
                      </td>
                    </tr>
                    {(subsByParent[row.category_id] ?? []).map((sub: any) => {
                      const subRolloverBalance = parseFloat(sub.rollover_balance || "0");
                      const subBudgeted = parseFloat(sub.budgeted || "0");
                      const subAvailable = sub.rollover_enabled ? subBudgeted + subRolloverBalance : subBudgeted;
                      const subActualTotal = parseFloat(sub.actual_total || "0");
                      const subVariance = subAvailable - subActualTotal;
                      return (
                        <tr key={sub.category_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                          <td className="pl-8 pr-4 py-2 text-gray-600 dark:text-gray-400">
                            <div className="flex items-center gap-2">
                              {sub.category_name}
                              <label className="flex items-center gap-1 cursor-pointer" title="Enable rollover for this subcategory">
                                <input
                                  type="checkbox"
                                  checked={!!sub.rollover_enabled}
                                  onChange={e => rolloverToggleMut.mutate({ id: sub.category_id, enabled: e.target.checked })}
                                  className="w-3 h-3 accent-indigo-500"
                                />
                                <span className="text-xs font-normal text-gray-400">rollover</span>
                              </label>
                            </div>
                          </td>
                          <td className="px-4 py-2 text-right text-gray-400 text-xs">
                            {editId === sub.category_id ? (
                              <div className="flex items-center justify-end gap-1">
                                <input type="number" step="0.01" className="input w-20 py-1 text-right text-xs" value={editAmt} onChange={e => setEditAmt(e.target.value)} autoFocus />
                                <button onClick={() => saveEdit(sub.category_id)} className="text-green-600 hover:text-green-700"><Check size={12} /></button>
                                <button onClick={() => setEditId(null)} className="text-gray-400 hover:text-gray-600"><X size={12} /></button>
                              </div>
                            ) : (
                              <span className="text-blue-500">{subBudgeted > 0 ? fmt(subBudgeted) : "—"}</span>
                            )}
                          </td>
                          <td className="px-4 py-2 text-right text-xs">
                            {sub.rollover_enabled && subRolloverBalance > 0 ? (
                              <span className="text-amber-600 dark:text-amber-400">+{fmt(subRolloverBalance)}</span>
                            ) : (
                              <span className="text-gray-300 dark:text-gray-600">—</span>
                            )}
                          </td>
                          <td className="px-4 py-2 text-right text-gray-400 text-xs">
                            {subBudgeted > 0 || (sub.rollover_enabled && subRolloverBalance > 0) ? fmt(subAvailable) : "—"}
                          </td>
                          <td className="px-4 py-2 text-right text-gray-500 dark:text-gray-400 text-xs">{fmt(sub.actual_checking)}</td>
                          <td className="px-4 py-2 text-right text-gray-500 dark:text-gray-400 text-xs">{fmt(sub.actual_cards)}</td>
                          <td className="px-4 py-2 text-right text-gray-700 dark:text-gray-300 font-medium">{fmt(sub.actual_total)}</td>
                          <td className={`px-4 py-2 text-right text-xs ${subVariance < 0 ? "text-red-500" : "text-green-500"}`}>
                            {subBudgeted > 0 || (sub.rollover_enabled && subRolloverBalance > 0) ? fmt(subVariance) : "—"}
                          </td>
                          <td className="px-4 py-2">
                            <button onClick={() => { setEditId(sub.category_id); setEditAmt(sub.budgeted); }} className="text-gray-300 hover:text-indigo-500"><Pencil size={12} /></button>
                          </td>
                        </tr>
                      );
                    })}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      <p className="text-xs text-gray-400 dark:text-gray-500">Budgets set here apply to all months. Enable "rollover" on a category to carry unspent amounts forward each month.</p>
      {showHelp && <HelpPanel title="Budget" body={"Set monthly spending targets for each category.\n\nActual spending is pulled from your imported transactions and credit card charges.\n\nEnable rollover on a category to carry unspent amounts into the next month — great for irregular expenses like car repair or medical bills."} onClose={() => setShowHelp(false)} />}
    </div>
  );
}

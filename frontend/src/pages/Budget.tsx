import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { budgetApi } from "../api";
import { fmt } from "../lib/utils";
import { Pencil, Check, X } from "lucide-react";

export default function Budget() {
  const now = new Date();
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

  function saveEdit(catId: number) {
    upsertMut.mutate({ category_id: catId, year, month: 0, budgeted_amount: parseFloat(editAmt) });
  }

  const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  // Separate top-level vs sub-category rows from overview
  const tops = overview.filter((r: any) => !r.parent_id);
  const subs = overview.filter((r: any) => r.parent_id);
  const subsByParent: Record<number, any[]> = {};
  subs.forEach((s: any) => { (subsByParent[s.parent_id] ??= []).push(s); });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-900">Budget</h2>
          <p className="text-sm text-gray-500">Set monthly targets and track actual spending</p>
        </div>
        <div className="flex gap-2">
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
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Category</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Budget</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Checking</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Cards</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Total</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Left</th>
                <th className="px-4 py-3 w-10"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {tops.map((row: any) => (
                <React.Fragment key={row.category_id}>
                  <tr className="bg-gray-50/60">
                    <td className="px-4 py-2.5 font-semibold text-gray-900">{row.category_name}</td>
                    <td className="px-4 py-2.5 text-right">
                      {editId === row.category_id ? (
                        <div className="flex items-center justify-end gap-1">
                          <input type="number" step="0.01" className="input w-24 py-1 text-right" value={editAmt} onChange={e => setEditAmt(e.target.value)} autoFocus />
                          <button onClick={() => saveEdit(row.category_id)} className="text-green-600 hover:text-green-700"><Check size={14} /></button>
                          <button onClick={() => setEditId(null)} className="text-gray-400 hover:text-gray-600"><X size={14} /></button>
                        </div>
                      ) : (
                        <span className="text-blue-600 font-medium">{parseFloat(row.budgeted) > 0 ? fmt(row.budgeted) : "—"}</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-right text-gray-600">{fmt(row.actual_checking)}</td>
                    <td className="px-4 py-2.5 text-right text-gray-600">{fmt(row.actual_cards)}</td>
                    <td className="px-4 py-2.5 text-right font-semibold text-gray-900">{fmt(row.actual_total)}</td>
                    <td className={`px-4 py-2.5 text-right font-semibold ${parseFloat(row.variance) < 0 ? "text-red-600" : "text-green-600"}`}>
                      {parseFloat(row.budgeted) > 0 ? fmt(row.variance) : "—"}
                    </td>
                    <td className="px-4 py-2.5">
                      <button onClick={() => { setEditId(row.category_id); setEditAmt(row.budgeted); }} className="text-gray-300 hover:text-indigo-500"><Pencil size={13} /></button>
                    </td>
                  </tr>
                  {(subsByParent[row.category_id] ?? []).map((sub: any) => (
                    <tr key={sub.category_id} className="hover:bg-gray-50">
                      <td className="pl-8 pr-4 py-2 text-gray-600">{sub.category_name}</td>
                      <td className="px-4 py-2 text-right text-gray-400 text-xs">
                        {parseFloat(sub.budgeted) > 0 ? fmt(sub.budgeted) : "—"}
                      </td>
                      <td className="px-4 py-2 text-right text-gray-500 text-xs">{fmt(sub.actual_checking)}</td>
                      <td className="px-4 py-2 text-right text-gray-500 text-xs">{fmt(sub.actual_cards)}</td>
                      <td className="px-4 py-2 text-right text-gray-700 font-medium">{fmt(sub.actual_total)}</td>
                      <td className={`px-4 py-2 text-right text-xs ${parseFloat(sub.variance) < 0 ? "text-red-500" : "text-green-500"}`}>
                        {parseFloat(sub.budgeted) > 0 ? fmt(sub.variance) : "—"}
                      </td>
                      <td className="px-4 py-2">
                        <button onClick={() => { setEditId(sub.category_id); setEditAmt(sub.budgeted); }} className="text-gray-300 hover:text-indigo-500"><Pencil size={12} /></button>
                      </td>
                    </tr>
                  ))}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <p className="text-xs text-gray-400">Budgets set here apply to all months (month=0). Month-specific overrides will be supported in a future release.</p>
    </div>
  );
}

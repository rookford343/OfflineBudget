import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { transactionsApi, accountsApi, categoriesApi } from "../api";
import { fmt, today, firstOfMonth } from "../lib/utils";
import { Plus, Trash2, X } from "lucide-react";

const emptyForm = { account_id: "", category_id: "", date: today(), amount: "", description: "", notes: "" };

export default function Transactions() {
  const qc = useQueryClient();
  const [start, setStart] = useState(firstOfMonth());
  const [end, setEnd] = useState(today());
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ ...emptyForm });
  const [deleteId, setDeleteId] = useState<number | null>(null);

  const { data: txns = [], isLoading } = useQuery({
    queryKey: ["transactions", start, end],
    queryFn: () => transactionsApi.list({ start, end }),
  });
  const { data: accounts = [] } = useQuery({ queryKey: ["accounts"], queryFn: accountsApi.list });
  const { data: categories = [] } = useQuery({ queryKey: ["categories"], queryFn: categoriesApi.list });
  const allCats = categories.flatMap((c: any) => [c, ...(c.children ?? [])]);

  const createMut = useMutation({
    mutationFn: transactionsApi.create,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["transactions"] }); qc.invalidateQueries({ queryKey: ["accounts"] }); setShowForm(false); setForm({ ...emptyForm }); },
  });
  const deleteMut = useMutation({
    mutationFn: transactionsApi.remove,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["transactions"] }); qc.invalidateQueries({ queryKey: ["accounts"] }); setDeleteId(null); },
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    createMut.mutate({ ...form, account_id: parseInt(form.account_id), category_id: form.category_id ? parseInt(form.category_id) : null, amount: parseFloat(form.amount) });
  }

  const accountMap = Object.fromEntries(accounts.map((a: any) => [a.id, a.name]));
  const catMap = Object.fromEntries(allCats.map((c: any) => [c.id, c.name]));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-900">Transactions</h2>
          <p className="text-sm text-gray-500">{txns.length} transaction{txns.length !== 1 ? "s" : ""}</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <input type="date" className="input w-auto" value={start} onChange={e => setStart(e.target.value)} />
          <span className="self-center text-gray-400">→</span>
          <input type="date" className="input w-auto" value={end} onChange={e => setEnd(e.target.value)} />
          <button onClick={() => setShowForm(true)} className="btn-primary"><Plus size={16} /> Add</button>
        </div>
      </div>

      <div className="card overflow-hidden p-0">
        {isLoading && <p className="text-sm text-gray-400 text-center py-8">Loading…</p>}
        {!isLoading && txns.length === 0 && <p className="text-sm text-gray-400 text-center py-8">No transactions in this period</p>}
        {txns.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase hidden sm:table-cell">Category</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase hidden md:table-cell">Account</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Amount</th>
                <th className="px-4 py-3 w-10"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {txns.map((t: any) => (
                <tr key={t.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                    {new Date(t.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                  </td>
                  <td className="px-4 py-3 text-gray-900 max-w-xs truncate">{t.description}</td>
                  <td className="px-4 py-3 text-gray-500 hidden sm:table-cell">{catMap[t.category_id] ?? "—"}</td>
                  <td className="px-4 py-3 text-gray-500 hidden md:table-cell">{accountMap[t.account_id] ?? "—"}</td>
                  <td className={`px-4 py-3 text-right font-semibold tabular-nums ${parseFloat(t.amount) >= 0 ? "text-green-600" : "text-red-600"}`}>
                    {parseFloat(t.amount) >= 0 ? "+" : ""}{fmt(t.amount)}
                  </td>
                  <td className="px-4 py-3">
                    <button onClick={() => setDeleteId(t.id)} className="text-gray-300 hover:text-red-500"><Trash2 size={14} /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-md">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900">Add Transaction</h3>
              <button onClick={() => setShowForm(false)} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <form onSubmit={submit} className="space-y-3">
              <div>
                <label className="label">Account</label>
                <select className="input" value={form.account_id} onChange={e => setForm({ ...form, account_id: e.target.value })} required>
                  <option value="">Select…</option>
                  {accounts.map((a: any) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              </div>
              <div><label className="label">Date</label><input type="date" className="input" value={form.date} onChange={e => setForm({ ...form, date: e.target.value })} required /></div>
              <div><label className="label">Description</label><input className="input" placeholder="Duke Energy bill" value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} required /></div>
              <div>
                <label className="label">Amount (negative = expense)</label>
                <input type="number" step="0.01" className="input" placeholder="-180.00" value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })} required />
              </div>
              <div>
                <label className="label">Category</label>
                <select className="input" value={form.category_id} onChange={e => setForm({ ...form, category_id: e.target.value })}>
                  <option value="">None</option>
                  {allCats.map((c: any) => <option key={c.id} value={c.id}>{c.parent_id ? "  " : ""}{c.name}</option>)}
                </select>
              </div>
              <div><label className="label">Notes</label><input className="input" value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /></div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1">Add Transaction</button>
                <button type="button" onClick={() => setShowForm(false)} className="btn-secondary flex-1">Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {deleteId && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm text-center">
            <h3 className="font-bold text-gray-900 mb-1">Delete this transaction?</h3>
            <p className="text-sm text-gray-500 mb-5">This will reverse its effect on the account balance.</p>
            <div className="flex gap-3">
              <button onClick={() => deleteMut.mutate(deleteId)} className="btn-danger flex-1">Delete</button>
              <button onClick={() => setDeleteId(null)} className="btn-secondary flex-1">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

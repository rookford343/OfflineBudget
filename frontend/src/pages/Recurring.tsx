import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { recurringApi, accountsApi, categoriesApi } from "../api";
import { fmt } from "../lib/utils";
import { Plus, Pencil, Trash2, TrendingUp, TrendingDown, X, Sparkles, HelpCircle } from "lucide-react";
import HelpPanel from "../components/HelpPanel";

const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];

const emptyForm = { name: "", amount: "", type: "expense", frequency: "monthly", month_of_year: "1", account_id: "", category_id: "", day_of_month: "15", start_date: new Date().toISOString().slice(0, 10), end_date: "", notes: "" };

export default function Recurring() {
  const qc = useQueryClient();
  const [showHelp, setShowHelp] = useState(false);
  const { data: items = [] } = useQuery<any[]>({ queryKey: ["recurring"], queryFn: () => recurringApi.list(false) });
  const { data: accounts = [] } = useQuery({ queryKey: ["accounts"], queryFn: accountsApi.list });
  const { data: categories = [] } = useQuery({ queryKey: ["categories"], queryFn: categoriesApi.list });
  const allCats = categories.flatMap((c: any) => [c, ...(c.children ?? [])]);

  const { data: suggestions = [] } = useQuery<any[]>({
    queryKey: ["recurring-suggestions"],
    queryFn: () => recurringApi.suggestions(),
    staleTime: 5 * 60 * 1000,
  });
  const [dismissedSuggestions, setDismissedSuggestions] = useState<Set<string>>(new Set());

  const [showForm, setShowForm] = useState(false);
  const [editItem, setEditItem] = useState<any | null>(null);
  const [form, setForm] = useState({ ...emptyForm });
  const [deleteId, setDeleteId] = useState<number | null>(null);

  const createMut = useMutation({ mutationFn: recurringApi.create, onSuccess: done });
  const updateMut = useMutation({ mutationFn: ({ id, data }: any) => recurringApi.update(id, data), onSuccess: done });
  const deleteMut = useMutation({ mutationFn: recurringApi.remove, onSuccess: () => { qc.invalidateQueries({ queryKey: ["recurring"] }); setDeleteId(null); } });

  function done() { qc.invalidateQueries({ queryKey: ["recurring"] }); setShowForm(false); setEditItem(null); }
  function openNew() { setForm({ ...emptyForm, account_id: accounts[0]?.id?.toString() ?? "" }); setEditItem(null); setShowForm(true); }
  function openEdit(i: any) { setEditItem(i); setForm({ name: i.name, amount: i.amount, type: i.type, frequency: i.frequency ?? "monthly", month_of_year: String(i.month_of_year ?? "1"), account_id: String(i.account_id), category_id: String(i.category_id ?? ""), day_of_month: String(i.day_of_month), start_date: i.start_date, end_date: i.end_date ?? "", notes: i.notes ?? "" }); setShowForm(true); }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const data = { ...form, amount: parseFloat(form.amount), account_id: parseInt(form.account_id), category_id: form.category_id ? parseInt(form.category_id) : null, day_of_month: parseInt(form.day_of_month), month_of_year: form.frequency === "yearly" ? parseInt(form.month_of_year) : null, end_date: form.end_date || null };
    if (editItem) updateMut.mutate({ id: editItem.id, data });
    else createMut.mutate(data);
  }

  const visibleSuggestions = suggestions.filter((s: any) => !dismissedSuggestions.has(s.description));

  const income = items.filter((i: any) => i.type === "income" && i.is_active);
  const expenses = items.filter((i: any) => i.type === "expense" && i.is_active);
  const inactive = items.filter((i: any) => !i.is_active);
  const monthlyIncome = income.reduce((s: number, i: any) => s + (i.frequency === "yearly" ? parseFloat(i.amount) / 12 : parseFloat(i.amount)), 0);
  const monthlyExpenses = expenses.reduce((s: number, i: any) => s + (i.frequency === "yearly" ? parseFloat(i.amount) / 12 : parseFloat(i.amount)), 0);

  function ItemRow({ item }: { item: any }) {
    const isYearly = item.frequency === "yearly";
    const dayLabel = isYearly
      ? `${MONTHS[(item.month_of_year ?? 1) - 1]} ${item.day_of_month === 0 ? "last day" : item.day_of_month} each year`
      : `${item.day_of_month === 0 ? "Last day" : `Day ${item.day_of_month}`} each month`;
    return (
      <div className="flex items-center justify-between py-2.5 border-b border-gray-50 last:border-0">
        <div>
          <p className="text-sm font-medium text-gray-900">{item.name}</p>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className={isYearly ? "badge-amber" : "badge-blue"}>{isYearly ? "yearly" : "monthly"}</span>
            <span className="text-xs text-gray-400">{dayLabel}</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <span className={`text-sm font-bold tabular-nums ${item.type === "income" ? "text-green-600" : "text-red-600"}`}>
              {item.type === "income" ? "+" : "-"}{fmt(item.amount)}
            </span>
            {isYearly && <p className="text-xs text-gray-400 tabular-nums">{fmt(parseFloat(item.amount) / 12)}/mo</p>}
          </div>
          <button onClick={() => openEdit(item)} className="btn-ghost p-1"><Pencil size={14} /></button>
          <button onClick={() => setDeleteId(item.id)} className="btn-ghost p-1 text-red-500 hover:bg-red-50"><Trash2 size={14} /></button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-900 flex items-center gap-1.5">Recurring Items <button onClick={() => setShowHelp(true)} className="text-gray-400 hover:text-indigo-500 font-normal"><HelpCircle size={15} /></button></h2>
          <p className="text-sm text-gray-500">Income and bills that repeat monthly</p>
        </div>
        <button onClick={openNew} className="btn-primary"><Plus size={16} /> Add Item</button>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="stat-card">
          <span className="stat-label">Monthly Income</span>
          <span className="stat-value text-green-600">{fmt(monthlyIncome)}</span>
          <span className="text-xs text-gray-400">yearly items averaged</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Monthly Expenses</span>
          <span className="stat-value text-red-600">{fmt(monthlyExpenses)}</span>
          <span className="text-xs text-gray-400">yearly items averaged</span>
        </div>
      </div>

      {(income.length > 0 || expenses.length > 0) && (
        <div className={`card flex items-center justify-between ${monthlyIncome - monthlyExpenses >= 0 ? "bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800" : "bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800"}`}>
          <div>
            <p className="text-sm font-semibold text-gray-900 dark:text-white">Monthly Cash Flow</p>
            <p className="text-xs text-gray-500 dark:text-gray-400">{fmt(monthlyIncome)} income − {fmt(monthlyExpenses)} expenses</p>
          </div>
          <p className={`text-xl font-bold tabular-nums ${monthlyIncome - monthlyExpenses >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
            {monthlyIncome - monthlyExpenses >= 0 ? "+" : ""}{fmt(monthlyIncome - monthlyExpenses)}
          </p>
        </div>
      )}

      {/* Detected patterns */}
      {visibleSuggestions.length > 0 && (
        <div className="card">
          <h3 className="font-semibold text-gray-900 dark:text-white mb-1 flex items-center gap-2">
            <Sparkles size={16} className="text-indigo-500" />
            Suggested Recurring Items
          </h3>
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
            Detected from your transaction history — add any that should be tracked.
          </p>
          <div className="space-y-2">
            {visibleSuggestions.map((s: any) => (
              <div key={s.description} className="flex items-center justify-between py-2 border-b border-gray-50 dark:border-gray-800 last:border-0 gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{s.description}</p>
                  <p className="text-xs text-gray-400 dark:text-gray-500 capitalize">{s.frequency} · {s.occurrences} occurrences</p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-sm font-semibold text-red-600 dark:text-red-400 tabular-nums">
                    -{fmt(parseFloat(s.median_amount))}
                  </span>
                  <button
                    onClick={() => {
                      const amount = parseFloat(s.median_amount).toFixed(2);
                      setForm({
                        ...emptyForm,
                        name: s.description,
                        amount,
                        type: "expense",
                        frequency: s.frequency,
                        account_id: accounts[0]?.id?.toString() ?? "",
                      });
                      setEditItem(null);
                      setShowForm(true);
                    }}
                    className="btn-primary py-1 px-2 text-xs"
                  >
                    Add
                  </button>
                  <button
                    onClick={() => setDismissedSuggestions(prev => new Set([...prev, s.description]))}
                    className="text-gray-300 dark:text-gray-600 hover:text-gray-500 dark:hover:text-gray-400"
                    title="Dismiss"
                  >
                    <X size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid md:grid-cols-2 gap-6">
        <div className="card">
          <h3 className="font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2"><TrendingUp size={16} className="text-green-500" /> Income ({income.length})</h3>
          {income.length === 0 ? <p className="text-sm text-gray-400 py-4 text-center">No income sources yet</p> : income.sort((a: any, b: any) => a.day_of_month - b.day_of_month).map((i: any) => <ItemRow key={i.id} item={i} />)}
        </div>
        <div className="card">
          <h3 className="font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2"><TrendingDown size={16} className="text-red-500" /> Bills & Expenses ({expenses.length})</h3>
          {expenses.length === 0 ? <p className="text-sm text-gray-400 py-4 text-center">No recurring bills yet</p> : expenses.sort((a: any, b: any) => a.day_of_month - b.day_of_month).map((i: any) => <ItemRow key={i.id} item={i} />)}
        </div>
      </div>

      {inactive.length > 0 && (
        <div className="card opacity-60">
          <h3 className="font-semibold text-gray-500 mb-3">Inactive ({inactive.length})</h3>
          {inactive.map((i: any) => <ItemRow key={i.id} item={i} />)}
        </div>
      )}

      {/* Add/Edit form modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-md max-h-[90vh] overflow-y-auto">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900">{editItem ? "Edit Recurring Item" : "Add Recurring Item"}</h3>
              <button onClick={() => setShowForm(false)} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <form onSubmit={submit} className="space-y-3">
              <div>
                <label className="label">Type</label>
                <div className="flex rounded-lg bg-gray-100 p-1">
                  {["income", "expense"].map(t => (
                    <button key={t} type="button" onClick={() => setForm({ ...form, type: t })}
                      className={`flex-1 py-1.5 text-sm font-medium rounded-md transition-colors capitalize ${form.type === t ? "bg-white shadow-sm text-gray-900" : "text-gray-500"}`}>
                      {t}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="label">Frequency</label>
                <div className="flex rounded-lg bg-gray-100 p-1">
                  {["monthly", "yearly"].map(f => (
                    <button key={f} type="button" onClick={() => setForm({ ...form, frequency: f })}
                      className={`flex-1 py-1.5 text-sm font-medium rounded-md transition-colors capitalize ${form.frequency === f ? "bg-white shadow-sm text-gray-900" : "text-gray-500"}`}>
                      {f}
                    </button>
                  ))}
                </div>
              </div>
              {form.frequency === "yearly" && (
                <div>
                  <label className="label">Month</label>
                  <select className="input" value={form.month_of_year} onChange={e => setForm({ ...form, month_of_year: e.target.value })} required>
                    {MONTHS.map((m, i) => <option key={i + 1} value={i + 1}>{m}</option>)}
                  </select>
                </div>
              )}
              <div><label className="label">Name</label><input className="input" placeholder="Duke Electric" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} required /></div>
              <div><label className="label">Amount</label><input type="number" step="0.01" className="input" placeholder="180.00" value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })} required /></div>
              <div>
                <label className="label">Account</label>
                <select className="input" value={form.account_id} onChange={e => setForm({ ...form, account_id: e.target.value })} required>
                  <option value="">Select…</option>
                  {accounts.map((a: any) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              </div>
              <div>
                <label className="label">Category</label>
                <select className="input" value={form.category_id} onChange={e => setForm({ ...form, category_id: e.target.value })}>
                  <option value="">None</option>
                  {allCats.filter((c: any) => c.type === form.type).map((c: any) => (
                    <option key={c.id} value={c.id}>{c.parent_id ? "  " : ""}{c.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Day of Month (0 = last day)</label>
                <input type="number" min="0" max="31" className="input" value={form.day_of_month} onChange={e => setForm({ ...form, day_of_month: e.target.value })} required />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div><label className="label">Start Date</label><input type="date" className="input" value={form.start_date} onChange={e => setForm({ ...form, start_date: e.target.value })} required /></div>
                <div><label className="label">End Date (optional)</label><input type="date" className="input" value={form.end_date} onChange={e => setForm({ ...form, end_date: e.target.value })} /></div>
              </div>
              <div><label className="label">Notes</label><input className="input" value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /></div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1">{editItem ? "Save" : "Add"}</button>
                <button type="button" onClick={() => setShowForm(false)} className="btn-secondary flex-1">Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {deleteId && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm text-center">
            <h3 className="font-bold text-gray-900 mb-1">Deactivate this item?</h3>
            <p className="text-sm text-gray-500 mb-5">It won't appear in future forecasts but history is kept.</p>
            <div className="flex gap-3">
              <button onClick={() => deleteMut.mutate(deleteId)} className="btn-danger flex-1">Deactivate</button>
              <button onClick={() => setDeleteId(null)} className="btn-secondary flex-1">Cancel</button>
            </div>
          </div>
        </div>
      )}
      {showHelp && <HelpPanel title="Recurring Items" body={"Recurring items drive the forecast engine and calendar.\n\nEach item has a day of the month, amount, and type (income or expense). Monthly items fire every month; yearly items fire in their designated month.\n\nItems falling on a weekend are automatically shifted to the preceding Friday in the forecast."} onClose={() => setShowHelp(false)} />}
    </div>
  );
}

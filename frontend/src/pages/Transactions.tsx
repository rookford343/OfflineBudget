import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { transactionsApi, accountsApi, categoriesApi, cardsApi, reconciliationApi } from "../api";
import { fmt, today, firstOfMonth } from "../lib/utils";
import { Plus, Trash2, X, HelpCircle, CheckCircle2, AlertCircle } from "lucide-react";
import HelpPanel from "../components/HelpPanel";

type TxnTab = "checking" | "card" | "reconcile";

interface CategoryCellProps {
  txnId: number;
  catId: number | null;
  onSave: (id: number | null) => void;
  editingCatId: number | null;
  setEditingCatId: (id: number | null) => void;
  allCats: any[];
  catMap: Record<number, string>;
}

function CategoryCell({ txnId, catId, onSave, editingCatId, setEditingCatId, allCats, catMap }: CategoryCellProps) {
  const isEditing = editingCatId === txnId;
  if (isEditing) {
    return (
      <select
        autoFocus
        className="input py-0.5 text-xs"
        defaultValue={catId ?? ""}
        onBlur={() => setEditingCatId(null)}
        onChange={e => {
          const val = e.target.value;
          onSave(val === "" ? null : parseInt(val));
        }}
      >
        <option value="">No category</option>
        {allCats.map((c: any) => (
          <option key={c.id} value={c.id}>{c.parent_id ? "  " : ""}{c.name}</option>
        ))}
      </select>
    );
  }
  return (
    <button
      onClick={() => setEditingCatId(txnId)}
      className={`px-2 py-0.5 rounded text-xs font-medium transition-colors hover:opacity-80 ${
        catId ? "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300" : "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400"
      }`}
    >
      {catId ? catMap[catId] ?? "—" : "Uncategorized"}
    </button>
  );
}

const emptyForm = { account_id: "", category_id: "", date: today(), amount: "", description: "", notes: "" };

export default function Transactions() {
  const qc = useQueryClient();
  const [showHelp, setShowHelp] = useState(false);
  const [txnTab, setTxnTab] = useState<TxnTab>("checking");
  const [start, setStart] = useState(firstOfMonth());
  const [end, setEnd] = useState(today());
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ ...emptyForm });
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [editingCatId, setEditingCatId] = useState<number | null>(null);
  const [editingNotesId, setEditingNotesId] = useState<number | null>(null);
  const [notesValue, setNotesValue] = useState("");
  const [selectedCardId, setSelectedCardId] = useState<number | null>(null);
  const [reconcileAccountId, setReconcileAccountId] = useState<number | null>(null);
  const now = new Date();
  const [reconcileYear, setReconcileYear] = useState(now.getFullYear());
  const [reconcileMonth, setReconcileMonth] = useState(now.getMonth() + 1);

  const { data: txns = [], isLoading } = useQuery({
    queryKey: ["transactions", start, end],
    queryFn: () => transactionsApi.list({ start, end }),
    enabled: txnTab === "checking",
  });
  const { data: accounts = [] } = useQuery({ queryKey: ["accounts"], queryFn: accountsApi.list });
  const { data: categories = [] } = useQuery({ queryKey: ["categories"], queryFn: categoriesApi.list });
  const { data: cards = [] } = useQuery({ queryKey: ["cards"], queryFn: cardsApi.list });

  const activeCardId = selectedCardId ?? (cards[0]?.id ?? null);

  const { data: cardTxns = [], isLoading: cardLoading } = useQuery({
    queryKey: ["card-transactions", activeCardId, start, end],
    queryFn: () => cardsApi.transactions(activeCardId!, { start, end }),
    enabled: txnTab === "card" && !!activeCardId,
  });

  const activeReconcileAccountId = reconcileAccountId ?? ((accounts as any[]).filter((a: any) => a.type === "checking")[0]?.id ?? null);
  const { data: reconcileData, isLoading: reconcileLoading } = useQuery({
    queryKey: ["reconcile", activeReconcileAccountId, reconcileYear, reconcileMonth],
    queryFn: () => reconciliationApi.get(activeReconcileAccountId!, reconcileYear, reconcileMonth),
    enabled: txnTab === "reconcile" && !!activeReconcileAccountId,
  });

  const allCats = categories.flatMap((c: any) => [c, ...(c.children ?? [])]);

  const createMut = useMutation({
    mutationFn: transactionsApi.create,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      setShowForm(false);
      setForm({ ...emptyForm });
    },
  });
  const deleteMut = useMutation({
    mutationFn: transactionsApi.remove,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      setDeleteId(null);
    },
  });
  const updateCatMut = useMutation({
    mutationFn: ({ id, data }: any) => transactionsApi.update(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      setEditingCatId(null);
    },
  });
  const updateNotesMut = useMutation({
    mutationFn: ({ id, notes }: { id: number; notes: string | null }) => transactionsApi.update(id, { notes }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["transactions"] }); setEditingNotesId(null); },
  });
  const updateCardCatMut = useMutation({
    mutationFn: ({ cardId, txnId, data }: any) => cardsApi.updateTransaction(cardId, txnId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["card-transactions"] });
      setEditingCatId(null);
    },
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    createMut.mutate({
      ...form,
      account_id: parseInt(form.account_id),
      category_id: form.category_id ? parseInt(form.category_id) : null,
      amount: parseFloat(form.amount),
    });
  }

  function handleCatChange(txnId: number, catId: number | null) {
    updateCatMut.mutate({ id: txnId, data: { category_id: catId } });
  }

  function handleCardCatChange(txnId: number, catId: number | null) {
    if (!activeCardId) return;
    updateCardCatMut.mutate({ cardId: activeCardId, txnId, data: { category_id: catId } });
  }

  const accountMap = Object.fromEntries(accounts.map((a: any) => [a.id, a.name]));
  const catMap = Object.fromEntries(allCats.map((c: any) => [c.id, c.name]));
  const loading = txnTab === "checking" ? isLoading : cardLoading;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100 flex items-center gap-1.5">Transactions <button onClick={() => setShowHelp(true)} className="text-gray-400 hover:text-indigo-500 font-normal"><HelpCircle size={15} /></button></h2>
          {txnTab !== "reconcile" && (
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {txnTab === "checking" ? `${txns.length} transaction${txns.length !== 1 ? "s" : ""}` : `${cardTxns.length} card charge${cardTxns.length !== 1 ? "s" : ""}`}
            </p>
          )}
        </div>
        <div className="flex gap-2 flex-wrap">
          <div className="flex rounded-lg bg-gray-100 dark:bg-gray-700 p-1">
            {(["checking", "card", "reconcile"] as TxnTab[]).map(t => (
              <button key={t} type="button"
                onClick={() => setTxnTab(t)}
                className={`px-3 py-1 text-xs font-medium rounded-md capitalize transition-colors ${txnTab === t ? "bg-white dark:bg-gray-800 shadow-sm text-gray-900 dark:text-gray-100" : "text-gray-500 dark:text-gray-400"}`}>
                {t === "checking" ? "Checking" : t === "card" ? "Credit Cards" : "Reconcile"}
              </button>
            ))}
          </div>
          {txnTab === "card" && cards.length > 0 && (
            <select className="input w-auto text-sm" value={activeCardId ?? ""} onChange={e => setSelectedCardId(parseInt(e.target.value))}>
              {cards.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
          {txnTab !== "reconcile" && <>
            <input type="date" className="input w-auto" value={start} onChange={e => setStart(e.target.value)} />
            <span className="self-center text-gray-400">→</span>
            <input type="date" className="input w-auto" value={end} onChange={e => setEnd(e.target.value)} />
          </>}
          {txnTab === "checking" && (
            <button onClick={() => setShowForm(true)} className="btn-primary"><Plus size={16} /> Add</button>
          )}
        </div>
      </div>

      {txnTab !== "reconcile" && <div className="card overflow-hidden p-0">
        {loading && <p className="text-sm text-gray-400 text-center py-8">Loading…</p>}

        {/* Checking transactions */}
        {txnTab === "checking" && !loading && (
          <>
            {txns.length === 0 && <p className="text-sm text-gray-400 text-center py-8">No transactions in this period</p>}
            {txns.length > 0 && (
              <table className="w-full text-sm">
                <thead className="bg-gray-50 dark:bg-gray-800/50 border-b border-gray-100 dark:border-gray-700">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase hidden sm:table-cell">Category</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase hidden md:table-cell">Account</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Amount</th>
                    <th className="px-4 py-3 w-10"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                  {txns.map((t: any) => (
                    <tr key={t.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                      <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                        {new Date(t.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                      </td>
                      <td className="px-4 py-3 text-gray-900 dark:text-gray-100 max-w-xs">
                        <div className="truncate">{t.description}</div>
                        {editingNotesId === t.id ? (
                          <input
                            autoFocus
                            className="input py-0.5 text-xs mt-0.5 w-full"
                            value={notesValue}
                            onChange={e => setNotesValue(e.target.value)}
                            onBlur={() => updateNotesMut.mutate({ id: t.id, notes: notesValue || null })}
                            onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); updateNotesMut.mutate({ id: t.id, notes: notesValue || null }); } if (e.key === "Escape") setEditingNotesId(null); }}
                            placeholder="Add note…"
                          />
                        ) : (
                          <button
                            onClick={() => { setEditingNotesId(t.id); setNotesValue(t.notes ?? ""); }}
                            className={`text-xs truncate block max-w-full text-left ${t.notes ? "text-gray-400 dark:text-gray-500 hover:text-indigo-500" : "text-gray-200 dark:text-gray-700 hover:text-gray-400"}`}
                          >
                            {t.notes || "add note…"}
                          </button>
                        )}
                      </td>
                      <td className="px-4 py-3 hidden sm:table-cell">
                        <CategoryCell txnId={t.id} catId={t.category_id} onSave={catId => handleCatChange(t.id, catId)} editingCatId={editingCatId} setEditingCatId={setEditingCatId} allCats={allCats} catMap={catMap} />
                      </td>
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
          </>
        )}

        {/* Card transactions */}
        {txnTab === "card" && !loading && (
          <>
            {cards.length === 0 && <p className="text-sm text-gray-400 text-center py-8">No credit cards configured</p>}
            {cards.length > 0 && cardTxns.length === 0 && <p className="text-sm text-gray-400 text-center py-8">No card transactions in this period</p>}
            {cardTxns.length > 0 && (
              <table className="w-full text-sm">
                <thead className="bg-gray-50 dark:bg-gray-800/50 border-b border-gray-100 dark:border-gray-700">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Merchant</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase hidden sm:table-cell">Category</th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Amount</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                  {cardTxns.map((t: any) => (
                    <tr key={t.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                      <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                        {new Date(t.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                      </td>
                      <td className="px-4 py-3 text-gray-900 dark:text-gray-100 max-w-xs truncate">{t.merchant}</td>
                      <td className="px-4 py-3 hidden sm:table-cell">
                        <CategoryCell txnId={t.id} catId={t.category_id} onSave={catId => handleCardCatChange(t.id, catId)} editingCatId={editingCatId} setEditingCatId={setEditingCatId} allCats={allCats} catMap={catMap} />
                      </td>
                      <td className="px-4 py-3 text-right font-semibold tabular-nums text-red-600">
                        {fmt(t.amount)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>}

      {/* Reconcile tab */}
      {txnTab === "reconcile" && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <select className="input w-auto text-sm" value={activeReconcileAccountId ?? ""} onChange={e => setReconcileAccountId(parseInt(e.target.value))}>
              {(accounts as any[]).filter((a: any) => a.type === "checking").map((a: any) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
            <select className="input w-auto text-sm" value={reconcileYear} onChange={e => setReconcileYear(parseInt(e.target.value))}>
              {[-1, 0, 1].map(d => { const y = new Date().getFullYear() + d; return <option key={y} value={y}>{y}</option>; })}
            </select>
            <select className="input w-auto text-sm" value={reconcileMonth} onChange={e => setReconcileMonth(parseInt(e.target.value))}>
              {["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"].map((m, i) => (
                <option key={i+1} value={i+1}>{m}</option>
              ))}
            </select>
          </div>
          {reconcileLoading && <p className="text-sm text-gray-400 text-center py-8">Loading…</p>}
          {!reconcileLoading && reconcileData && (
            <div className="space-y-4">
              {reconcileData.matched.length > 0 && (
                <div className="card p-0 overflow-hidden">
                  <div className="px-4 py-3 bg-green-50 dark:bg-green-900/20 border-b border-green-100 dark:border-green-800 flex items-center gap-2">
                    <CheckCircle2 size={15} className="text-green-600" />
                    <h3 className="text-sm font-semibold text-green-800 dark:text-green-300">Matched ({reconcileData.matched.length})</h3>
                  </div>
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 dark:bg-gray-800/50">
                      <tr>
                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase hidden sm:table-cell">Recurring Item</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Actual</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase hidden sm:table-cell">Expected</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase hidden md:table-cell">Variance</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                      {reconcileData.matched.map((item: any) => (
                        <tr key={item.transaction_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                          <td className="px-4 py-2 text-gray-500 whitespace-nowrap">
                            {new Date(item.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                          </td>
                          <td className="px-4 py-2 text-gray-900 dark:text-gray-100 max-w-xs truncate">{item.description}</td>
                          <td className="px-4 py-2 text-gray-500 hidden sm:table-cell">{item.recurring_name}</td>
                          <td className={`px-4 py-2 text-right font-semibold tabular-nums ${parseFloat(item.actual_amount) >= 0 ? "text-green-600" : "text-red-600"}`}>
                            {fmt(item.actual_amount)}
                          </td>
                          <td className="px-4 py-2 text-right text-gray-500 tabular-nums hidden sm:table-cell">{fmt(item.expected_amount)}</td>
                          <td className={`px-4 py-2 text-right tabular-nums hidden md:table-cell ${Math.abs(parseFloat(item.variance)) > 0.01 ? "text-amber-600" : "text-gray-400"}`}>
                            {parseFloat(item.variance) > 0 ? "+" : ""}{fmt(item.variance)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {reconcileData.unmatched_recurring.length > 0 && (
                <div className="card p-0 overflow-hidden">
                  <div className="px-4 py-3 bg-amber-50 dark:bg-amber-900/20 border-b border-amber-100 dark:border-amber-800 flex items-center gap-2">
                    <AlertCircle size={15} className="text-amber-600" />
                    <h3 className="text-sm font-semibold text-amber-800 dark:text-amber-300">Expected but not recorded ({reconcileData.unmatched_recurring.length})</h3>
                  </div>
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 dark:bg-gray-800/50">
                      <tr>
                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Recurring Item</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Expected Amount</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase hidden sm:table-cell">Expected Day</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                      {reconcileData.unmatched_recurring.map((item: any) => (
                        <tr key={item.recurring_item_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                          <td className="px-4 py-2 text-gray-900 dark:text-gray-100">{item.name}</td>
                          <td className="px-4 py-2 text-right font-semibold tabular-nums text-red-600">{fmt(item.expected_amount)}</td>
                          <td className="px-4 py-2 text-right text-gray-500 hidden sm:table-cell">{item.expected_day ?? "last"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {reconcileData.unmatched_transactions.length > 0 && (
                <div className="card p-0 overflow-hidden">
                  <div className="px-4 py-3 bg-blue-50 dark:bg-blue-900/20 border-b border-blue-100 dark:border-blue-800 flex items-center gap-2">
                    <AlertCircle size={15} className="text-blue-600" />
                    <h3 className="text-sm font-semibold text-blue-800 dark:text-blue-300">Unlinked transactions ({reconcileData.unmatched_transactions.length})</h3>
                  </div>
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 dark:bg-gray-800/50">
                      <tr>
                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
                        <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Amount</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                      {reconcileData.unmatched_transactions.map((item: any) => (
                        <tr key={item.transaction_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                          <td className="px-4 py-2 text-gray-500 whitespace-nowrap">
                            {new Date(item.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                          </td>
                          <td className="px-4 py-2 text-gray-900 dark:text-gray-100 max-w-xs truncate">{item.description}</td>
                          <td className={`px-4 py-2 text-right font-semibold tabular-nums ${parseFloat(item.amount) >= 0 ? "text-green-600" : "text-red-600"}`}>
                            {fmt(item.amount)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {!reconcileData.matched.length && !reconcileData.unmatched_recurring.length && !reconcileData.unmatched_transactions.length && (
                <div className="card text-center py-8 text-gray-400">No transactions or recurring items for this month.</div>
              )}
            </div>
          )}
          {!reconcileLoading && !reconcileData && <div className="card text-center py-8 text-gray-400">Select an account and month to reconcile.</div>}
        </div>
      )}

      {showForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-md">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900 dark:text-gray-100">Add Transaction</h3>
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

      {showHelp && <HelpPanel title="Transactions" body={"View and manage your transactions.\n\nChecking tab: all imported and manually entered checking account transactions. Click the category badge on any row to reassign it.\n\nCredit Cards tab: card charges by card. Click the category badge to reassign.\n\nUse the date range filter to narrow the view. The Add button creates a manual checking transaction."} onClose={() => setShowHelp(false)} />}

      {deleteId && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm text-center">
            <h3 className="font-bold text-gray-900 dark:text-gray-100 mb-1">Delete this transaction?</h3>
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

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { cardsApi, accountsApi } from "../api";
import { fmt, utilColor, utilBg, today } from "../lib/utils";
import { Plus, Pencil, Trash2, CreditCard as CardIcon, DollarSign, X, HelpCircle } from "lucide-react";
import HelpPanel from "../components/HelpPanel";

interface Card {
  id: number; name: string; last_four?: string; credit_limit: string;
  statement_day: number; due_day: number; current_balance: string;
  balance_due: string; next_payment_date?: string; monthly_spend_estimate?: string; is_active: boolean; notes?: string; utilization_pct: number;
}

const emptyCard = { name: "", last_four: "", credit_limit: "", statement_day: "26", due_day: "23", current_balance: "0", balance_due: "0", next_payment_date: "", monthly_spend_estimate: "", notes: "" };
const emptyPayment = { checking_account_id: "", date: today(), amount: "", notes: "" };

export default function CreditCards() {
  const qc = useQueryClient();
  const [showHelp, setShowHelp] = useState(false);
  const { data: cards = [], isLoading } = useQuery({ queryKey: ["credit-cards"], queryFn: cardsApi.list });
  const { data: accounts = [] } = useQuery({ queryKey: ["accounts"], queryFn: accountsApi.list });
  const checking = accounts.filter((a: any) => a.type === "checking");

  const [showForm, setShowForm] = useState(false);
  const [editCard, setEditCard] = useState<Card | null>(null);
  const [form, setForm] = useState({ ...emptyCard });
  const [payCard, setPayCard] = useState<Card | null>(null);
  const [payForm, setPayForm] = useState({ ...emptyPayment });
  const [deleteId, setDeleteId] = useState<number | null>(null);

  const createMut = useMutation({ mutationFn: cardsApi.create, onSuccess: () => { qc.invalidateQueries({ queryKey: ["credit-cards"] }); close(); } });
  const updateMut = useMutation({ mutationFn: ({ id, data }: any) => cardsApi.update(id, data), onSuccess: () => { qc.invalidateQueries({ queryKey: ["credit-cards"] }); close(); } });
  const deleteMut = useMutation({ mutationFn: cardsApi.remove, onSuccess: () => { qc.invalidateQueries({ queryKey: ["credit-cards"] }); setDeleteId(null); } });
  const payMut = useMutation({ mutationFn: ({ id, data }: any) => cardsApi.pay(id, data), onSuccess: () => { qc.invalidateQueries({ queryKey: ["credit-cards"] }); qc.invalidateQueries({ queryKey: ["accounts"] }); setPayCard(null); } });

  function openNew() { setForm({ ...emptyCard }); setEditCard(null); setShowForm(true); }
  function openEdit(c: Card) { setEditCard(c); setForm({ name: c.name, last_four: c.last_four || "", credit_limit: c.credit_limit, statement_day: String(c.statement_day), due_day: String(c.due_day), current_balance: c.current_balance, balance_due: c.balance_due, next_payment_date: c.next_payment_date || "", monthly_spend_estimate: c.monthly_spend_estimate || "", notes: c.notes || "" }); setShowForm(true); }
  function close() { setShowForm(false); setEditCard(null); }

  function submitCard(e: React.FormEvent) {
    e.preventDefault();
    const data = {
      ...form,
      credit_limit: parseFloat(form.credit_limit),
      statement_day: parseInt(form.statement_day),
      due_day: parseInt(form.due_day),
      current_balance: parseFloat(form.current_balance),
      balance_due: parseFloat(form.balance_due),
      next_payment_date: form.next_payment_date || null,
      monthly_spend_estimate: form.monthly_spend_estimate ? parseFloat(form.monthly_spend_estimate) : null,
    };
    if (editCard) updateMut.mutate({ id: editCard.id, data });
    else createMut.mutate(data);
  }

  function submitPayment(e: React.FormEvent) {
    e.preventDefault();
    if (!payCard) return;
    payMut.mutate({ id: payCard.id, data: { ...payForm, checking_account_id: parseInt(payForm.checking_account_id), amount: parseFloat(payForm.amount) } });
  }

  if (isLoading) return <div className="text-gray-400 text-sm">Loading…</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-900 flex items-center gap-1.5">Credit Cards <button onClick={() => setShowHelp(true)} className="text-gray-400 hover:text-indigo-500 font-normal"><HelpCircle size={15} /></button></h2>
          <p className="text-sm text-gray-500">{cards.length} card{cards.length !== 1 ? "s" : ""}</p>
        </div>
        <button onClick={openNew} className="btn-primary"><Plus size={16} /> Add Card</button>
      </div>

      {cards.length === 0 && !showForm && (
        <div className="card text-center py-12">
          <CardIcon className="mx-auto text-gray-300 mb-3" size={40} />
          <p className="text-gray-500 mb-4">No credit cards yet</p>
          <button onClick={openNew} className="btn-primary">Add Your First Card</button>
        </div>
      )}

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {cards.map((c: Card) => (
          <div key={c.id} className="card relative overflow-hidden">
            {/* Card graphic */}
            <div className="h-1 rounded-full mb-4" style={{ background: `linear-gradient(90deg, #6366f1, #8b5cf6)` }} />
            <div className="flex justify-between items-start mb-3">
              <div>
                <p className="font-bold text-gray-900">{c.name}</p>
                {c.last_four && <p className="text-xs text-gray-400">•••• {c.last_four}</p>}
              </div>
              <div className="flex gap-1">
                <button onClick={() => setPayCard(c)} className="btn-ghost p-1.5" title="Record payment"><DollarSign size={15} /></button>
                <button onClick={() => openEdit(c)} className="btn-ghost p-1.5"><Pencil size={15} /></button>
                <button onClick={() => setDeleteId(c.id)} className="btn-ghost p-1.5 text-red-500 hover:bg-red-50"><Trash2 size={15} /></button>
              </div>
            </div>

            <div className="space-y-2 mb-3">
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">Balance</span>
                <span className={`font-bold tabular-nums ${utilColor(c.utilization_pct)}`}>{fmt(c.current_balance)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">Amount Due</span>
                <span className={`font-semibold tabular-nums ${parseFloat(c.balance_due) > 0 ? "text-red-600" : "text-gray-400"}`}>{fmt(c.balance_due)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">Limit</span>
                <span className="text-gray-600 tabular-nums">{fmt(c.credit_limit)}</span>
              </div>
            </div>

            <div>
              <div className="flex justify-between text-xs text-gray-400 mb-1">
                <span>Utilization</span>
                <span className={utilColor(c.utilization_pct)}>{c.utilization_pct}%</span>
              </div>
              <div className="progress-bar">
                <div className={`progress-fill ${utilBg(c.utilization_pct)}`} style={{ width: `${Math.min(100, c.utilization_pct)}%` }} />
              </div>
            </div>

            <div className="mt-3 flex justify-between text-xs text-gray-400">
              <span>Statement: day {c.statement_day}</span>
              <span>Due: day {c.due_day}</span>
            </div>
            {c.next_payment_date && parseFloat(c.balance_due) > 0 && (
              <div className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                Pay {fmt(c.balance_due)} by {new Date(c.next_payment_date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Add / Edit card form */}
      {showForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-md max-h-[90vh] overflow-y-auto">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900">{editCard ? "Edit Card" : "Add Credit Card"}</h3>
              <button onClick={close} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <form onSubmit={submitCard} className="space-y-3">
              <div><label className="label">Card Name</label><input className="input" placeholder="Chase Sapphire" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} required /></div>
              <div><label className="label">Last 4 Digits (optional)</label><input className="input" placeholder="1234" maxLength={4} value={form.last_four} onChange={e => setForm({ ...form, last_four: e.target.value })} /></div>
              <div><label className="label">Credit Limit</label><input type="number" step="0.01" className="input" placeholder="10000" value={form.credit_limit} onChange={e => setForm({ ...form, credit_limit: e.target.value })} required /></div>
              <div className="grid grid-cols-2 gap-3">
                <div><label className="label">Statement Day</label><input type="number" min="1" max="31" className="input" value={form.statement_day} onChange={e => setForm({ ...form, statement_day: e.target.value })} required /></div>
                <div><label className="label">Due Day</label><input type="number" min="1" max="31" className="input" value={form.due_day} onChange={e => setForm({ ...form, due_day: e.target.value })} required /></div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div><label className="label">Current Balance</label><input type="number" step="0.01" className="input" value={form.current_balance} onChange={e => setForm({ ...form, current_balance: e.target.value })} /></div>
                <div><label className="label">Statement Balance Due</label><input type="number" step="0.01" className="input" placeholder="0.00" value={form.balance_due} onChange={e => setForm({ ...form, balance_due: e.target.value })} /></div>
              </div>
              <div><label className="label">Next Payment Date <span className="text-gray-400 font-normal">(for forecast)</span></label><input type="date" className="input" value={form.next_payment_date} onChange={e => setForm({ ...form, next_payment_date: e.target.value })} /></div>
              <div><label className="label">Monthly Spend Estimate <span className="text-gray-400 font-normal">(for forecast projection)</span></label><input type="number" step="0.01" className="input" placeholder="e.g. 800" value={form.monthly_spend_estimate} onChange={e => setForm({ ...form, monthly_spend_estimate: e.target.value })} /></div>
              <div><label className="label">Notes</label><input className="input" value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /></div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1">{editCard ? "Save Changes" : "Add Card"}</button>
                <button type="button" onClick={close} className="btn-secondary flex-1">Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Payment modal */}
      {payCard && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900">Record Payment — {payCard.name}</h3>
              <button onClick={() => setPayCard(null)} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <p className="text-sm text-gray-500 mb-4">Balance due: <strong className="text-red-600">{fmt(payCard.balance_due)}</strong></p>
            <form onSubmit={submitPayment} className="space-y-3">
              <div>
                <label className="label">Pay From (Checking Account)</label>
                <select className="input" value={payForm.checking_account_id} onChange={e => setPayForm({ ...payForm, checking_account_id: e.target.value })} required>
                  <option value="">Select account…</option>
                  {checking.map((a: any) => <option key={a.id} value={a.id}>{a.name} ({fmt(a.current_balance)})</option>)}
                </select>
              </div>
              <div><label className="label">Payment Date</label><input type="date" className="input" value={payForm.date} onChange={e => setPayForm({ ...payForm, date: e.target.value })} required /></div>
              <div><label className="label">Amount</label><input type="number" step="0.01" className="input" placeholder={payCard.balance_due} value={payForm.amount} onChange={e => setPayForm({ ...payForm, amount: e.target.value })} required /></div>
              <div><label className="label">Notes</label><input className="input" value={payForm.notes} onChange={e => setPayForm({ ...payForm, notes: e.target.value })} /></div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1">Record Payment</button>
                <button type="button" onClick={() => setPayCard(null)} className="btn-secondary flex-1">Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete confirm */}
      {deleteId && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm text-center">
            <Trash2 className="mx-auto text-red-400 mb-3" size={32} />
            <h3 className="font-bold text-gray-900 mb-1">Remove this card?</h3>
            <p className="text-sm text-gray-500 mb-5">This will hide it from your dashboard. Transaction history is preserved.</p>
            <div className="flex gap-3">
              <button onClick={() => deleteMut.mutate(deleteId)} className="btn-danger flex-1">Remove</button>
              <button onClick={() => setDeleteId(null)} className="btn-secondary flex-1">Cancel</button>
            </div>
          </div>
        </div>
      )}
      {showHelp && <HelpPanel title="Credit Cards" body={"Track credit card balances, utilization, and payments.\n\nImport card transactions via CSV to see spending by category.\n\nRecord payments to move money from a checking account to the card and reduce the balance due.\n\nUtilization percentage is highlighted when above 30%."} onClose={() => setShowHelp(false)} />}
    </div>
  );
}

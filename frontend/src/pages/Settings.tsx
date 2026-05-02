import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { accountsApi, categoriesApi, budgetApi, adminApi, authApi } from "../api";
import { fmt } from "../lib/utils";
import { getTheme, setTheme } from "../store/theme";
import { isAdmin } from "../store/auth";
import {
  Plus, Pencil, Trash2, X, Check, Moon, Sun, ChevronRight, ChevronDown,
  AlertTriangle, Shield, User, Activity, HelpCircle
} from "lucide-react";
import HelpPanel from "../components/HelpPanel";

const emptyAccount = { name: "", type: "checking", current_balance: "0", low_balance_threshold: "", notes: "" };
const emptyCat = { name: "", type: "expense", parent_id: "", color: "#6366f1" };
const emptyUser = { username: "", display_name: "", password: "", role: "viewer" };

const COLOR_SWATCHES = ["#6366f1", "#22c55e", "#ef4444", "#f59e0b", "#3b82f6", "#8b5cf6", "#ec4899", "#14b8a6"];

export default function Settings() {
  const qc = useQueryClient();
  const currentYear = new Date().getFullYear();
  const admin = isAdmin();

  // ── Queries ────────────────────────────────────────────────────────────────
  const { data: accounts = [] } = useQuery({ queryKey: ["accounts"], queryFn: accountsApi.list });
  const { data: categories = [] } = useQuery<any[]>({ queryKey: ["categories"], queryFn: categoriesApi.list });
  const { data: budgets = [] } = useQuery<any[]>({ queryKey: ["budget", currentYear], queryFn: () => budgetApi.list(currentYear) });
  const { data: users = [] } = useQuery<any[]>({ queryKey: ["admin-users"], queryFn: adminApi.listUsers, enabled: admin });
  const [logPage, setLogPage] = useState(0);
  const [logMethod, setLogMethod] = useState("");
  const { data: logData } = useQuery<any>({
    queryKey: ["audit-logs", logPage, logMethod],
    queryFn: () => adminApi.logs({ limit: 25, offset: logPage * 25, method: logMethod || undefined }),
    enabled: admin,
  });

  // ── Account state ──────────────────────────────────────────────────────────
  const [showAccForm, setShowAccForm] = useState(false);
  const [editAcc, setEditAcc] = useState<any | null>(null);
  const [accForm, setAccForm] = useState({ ...emptyAccount });
  const [deleteAccId, setDeleteAccId] = useState<number | null>(null);
  const [editBalId, setEditBalId] = useState<number | null>(null);
  const [newBal, setNewBal] = useState("");

  const createAccMut = useMutation({ mutationFn: accountsApi.create, onSuccess: () => { qc.invalidateQueries({ queryKey: ["accounts"] }); setShowAccForm(false); } });
  const updateAccMut = useMutation({ mutationFn: ({ id, data }: any) => accountsApi.update(id, data), onSuccess: () => { qc.invalidateQueries({ queryKey: ["accounts"] }); setEditAcc(null); setShowAccForm(false); setEditBalId(null); } });
  const deleteAccMut = useMutation({ mutationFn: accountsApi.remove, onSuccess: () => { qc.invalidateQueries({ queryKey: ["accounts"] }); setDeleteAccId(null); } });

  function submitAcc(e: React.FormEvent) {
    e.preventDefault();
    const data = {
      ...accForm,
      current_balance: parseFloat(accForm.current_balance),
      low_balance_threshold: accForm.low_balance_threshold ? parseFloat(accForm.low_balance_threshold) : null,
    };
    if (editAcc) updateAccMut.mutate({ id: editAcc.id, data });
    else createAccMut.mutate(data);
  }
  function openNewAcc() { setAccForm({ ...emptyAccount }); setEditAcc(null); setShowAccForm(true); }
  function openEditAcc(a: any) {
    setEditAcc(a);
    setAccForm({ name: a.name, type: a.type, current_balance: a.current_balance, low_balance_threshold: a.low_balance_threshold ?? "", notes: a.notes ?? "" });
    setShowAccForm(true);
  }

  // ── Category state ─────────────────────────────────────────────────────────
  const [showCatForm, setShowCatForm] = useState(false);
  const [editCat, setEditCat] = useState<any | null>(null);
  const [catForm, setCatForm] = useState({ ...emptyCat });
  const [deleteCatId, setDeleteCatId] = useState<number | null>(null);
  const [editBudgetCatId, setEditBudgetCatId] = useState<number | null>(null);
  const [budgetDraft, setBudgetDraft] = useState("");
  const [expandedCats, setExpandedCats] = useState<Set<number>>(new Set());

  const budgetMap: Record<number, string> = {};
  budgets.forEach((b: any) => { budgetMap[b.category_id] = b.budgeted_amount; });

  const createCatMut = useMutation({ mutationFn: categoriesApi.create, onSuccess: () => { qc.invalidateQueries({ queryKey: ["categories"] }); setShowCatForm(false); } });
  const updateCatMut = useMutation({ mutationFn: ({ id, data }: any) => categoriesApi.update(id, data), onSuccess: () => { qc.invalidateQueries({ queryKey: ["categories"] }); setEditCat(null); setShowCatForm(false); } });
  const deleteCatMut = useMutation({ mutationFn: categoriesApi.remove, onSuccess: () => { qc.invalidateQueries({ queryKey: ["categories"] }); setDeleteCatId(null); } });
  const upsertBudgetMut = useMutation({ mutationFn: budgetApi.upsert, onSuccess: () => { qc.invalidateQueries({ queryKey: ["budget", currentYear] }); setEditBudgetCatId(null); } });

  function submitCat(e: React.FormEvent) {
    e.preventDefault();
    const data = { ...catForm, parent_id: catForm.parent_id ? parseInt(catForm.parent_id) : null };
    if (editCat) updateCatMut.mutate({ id: editCat.id, data });
    else createCatMut.mutate(data);
  }
  function openNewCat(parentCat?: any) {
    setCatForm({ name: "", type: parentCat?.type ?? "expense", parent_id: parentCat?.id?.toString() ?? "", color: "#6366f1" });
    setEditCat(null);
    setShowCatForm(true);
  }
  function openEditCat(c: any) {
    setEditCat(c);
    setCatForm({ name: c.name, type: c.type, parent_id: c.parent_id?.toString() ?? "", color: c.color });
    setShowCatForm(true);
  }
  function saveBudget(catId: number) {
    upsertBudgetMut.mutate({ category_id: catId, year: currentYear, month: 0, budgeted_amount: parseFloat(budgetDraft) || 0 });
  }

  // ── Dark mode ──────────────────────────────────────────────────────────────
  const [dark, setDark] = useState(getTheme() === "dark");
  function toggleDark() { const next = !dark; setDark(next); setTheme(next); }

  // ── Social Security ────────────────────────────────────────────────────────
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: authApi.me });
  const [ssGross, setSsGross] = useState("");
  const [ssWageBase, setSsWageBase] = useState("");
  const [ssBonus, setSsBonus] = useState("");
  const [ssSaved, setSsSaved] = useState(false);
  const [showSsHelp, setShowSsHelp] = useState(false);
  React.useEffect(() => {
    if (me) {
      setSsGross(me.ss_gross_per_paycheck ?? "");
      setSsWageBase(me.ss_wage_base ?? "176100");
      setSsBonus(me.ss_bonus_ytd ?? "");
    }
  }, [me]);
  const updateMeMut = useMutation({
    mutationFn: authApi.updateMe,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["me"] }); setSsSaved(true); setTimeout(() => setSsSaved(false), 2000); },
  });

  // ── User management ────────────────────────────────────────────────────────
  const [showUserForm, setShowUserForm] = useState(false);
  const [userForm, setUserForm] = useState({ ...emptyUser });
  const createUserMut = useMutation({ mutationFn: adminApi.createUser, onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin-users"] }); setShowUserForm(false); setUserForm({ ...emptyUser }); } });
  const updateUserMut = useMutation({ mutationFn: ({ id, data }: any) => adminApi.updateUser(id, data), onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin-users"] }); } });

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">Settings</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">Manage accounts, categories, and preferences</p>
      </div>

      {/* ── Preferences ── */}
      <div className="card">
        <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-4">Preferences</h3>
        <div className="flex items-center justify-between py-2">
          <div className="flex items-center gap-3">
            {dark ? <Moon size={16} className="text-indigo-400" /> : <Sun size={16} className="text-amber-500" />}
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Dark Mode</span>
          </div>
          <button
            onClick={toggleDark}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${dark ? "bg-indigo-600" : "bg-gray-200"}`}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${dark ? "translate-x-6" : "translate-x-1"}`} />
          </button>
        </div>
      </div>

      {/* ── Social Security ── */}
      <div className="card">
        <div className="flex items-center gap-2 mb-1">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">Social Security Tax</h3>
          <button onClick={() => setShowSsHelp(true)} className="text-gray-400 hover:text-indigo-500"><HelpCircle size={15} /></button>
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">Track when you hit the SS wage base so you can plan for the resulting paycheck increase.</p>
        <div className="grid grid-cols-2 gap-4 max-w-md">
          <div>
            <label className="label">Gross Per Paycheck ($)</label>
            <input type="number" step="0.01" className="input" placeholder="5000" value={ssGross} onChange={e => setSsGross(e.target.value)} />
          </div>
          <div>
            <label className="label">SS Wage Base ($)</label>
            <input type="number" step="1" className="input" placeholder="176100" value={ssWageBase} onChange={e => setSsWageBase(e.target.value)} />
          </div>
          <div>
            <label className="label">YTD Bonus Subject to SS ($)</label>
            <input type="number" step="0.01" className="input" placeholder="0" value={ssBonus} onChange={e => setSsBonus(e.target.value)} />
          </div>
        </div>
        <div className="flex items-center gap-3 mt-3">
          <button
            onClick={() => updateMeMut.mutate({ ss_gross_per_paycheck: parseFloat(ssGross) || null, ss_wage_base: parseFloat(ssWageBase) || null, ss_bonus_ytd: parseFloat(ssBonus) || null })}
            disabled={updateMeMut.isPending}
            className="btn-primary text-sm"
          >
            {updateMeMut.isPending ? "Saving…" : "Save SS Settings"}
          </button>
          {ssSaved && <span className="text-sm text-green-600">Saved!</span>}
        </div>
      </div>
      {showSsHelp && <HelpPanel title="Social Security Tax" body={"Gross Per Paycheck: your total gross wages per paycheck before any deductions. This is used to estimate how many pay periods until you hit the SS wage base.\n\nSS Wage Base: the annual income limit above which Social Security tax is no longer withheld (default $176,100 for 2025). After reaching this limit, your paycheck increases by ~6.2% of gross.\n\nYTD Bonus Subject to SS: bonuses you've received this year that were subject to Social Security tax. Reduces the remaining wage base so the estimate stays accurate."} onClose={() => setShowSsHelp(false)} />}

      {/* ── Accounts ── */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">Accounts</h3>
          <button onClick={openNewAcc} className="btn-primary btn-sm text-xs px-3 py-1.5"><Plus size={14} /> Add Account</button>
        </div>
        <div className="divide-y divide-gray-100 dark:divide-gray-700">
          {accounts.map((a: any) => (
            <div key={a.id} className="py-3 flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{a.name}</p>
                  {a.low_balance_threshold && parseFloat(a.current_balance) < parseFloat(a.low_balance_threshold) && (
                    <AlertTriangle size={14} className="text-amber-500" />
                  )}
                </div>
                <p className="text-xs text-gray-500 dark:text-gray-400 capitalize">{a.type.replace("_", " ")}</p>
                {a.low_balance_threshold && (
                  <p className="text-xs text-amber-600 dark:text-amber-400">Alert below {fmt(a.low_balance_threshold)}</p>
                )}
              </div>
              <div className="flex items-center gap-3">
                {editBalId === a.id ? (
                  <div className="flex items-center gap-1">
                    <input type="number" step="0.01" className="input w-28 py-1 text-right" value={newBal} onChange={e => setNewBal(e.target.value)} autoFocus />
                    <button onClick={() => updateAccMut.mutate({ id: a.id, data: { current_balance: parseFloat(newBal) } })} className="text-green-600"><Check size={14} /></button>
                    <button onClick={() => setEditBalId(null)} className="text-gray-400"><X size={14} /></button>
                  </div>
                ) : (
                  <button onClick={() => { setEditBalId(a.id); setNewBal(a.current_balance); }} className="text-sm font-bold text-gray-900 dark:text-gray-100 tabular-nums hover:text-indigo-600 transition-colors">
                    {fmt(a.current_balance)}
                  </button>
                )}
                <button onClick={() => openEditAcc(a)} className="btn-ghost p-1.5"><Pencil size={14} /></button>
                <button onClick={() => setDeleteAccId(a.id)} className="btn-ghost p-1.5 text-red-400 hover:bg-red-50"><Trash2 size={14} /></button>
              </div>
            </div>
          ))}
          {accounts.length === 0 && <p className="text-sm text-gray-400 py-4 text-center">No accounts yet</p>}
        </div>
      </div>

      {/* ── Categories ── */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-semibold text-gray-900 dark:text-gray-100">Categories</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">Click a budget amount to edit it inline</p>
          </div>
          <button onClick={() => openNewCat()} className="btn-primary btn-sm text-xs px-3 py-1.5"><Plus size={14} /> Add Category</button>
        </div>
        <div className="space-y-1">
          {categories.map((cat: any) => (
            <div key={cat.id}>
              {/* Top-level row */}
              <div className="flex items-center gap-2 py-2 rounded-lg px-2 hover:bg-gray-50 dark:hover:bg-gray-700/50">
                <button onClick={() => setExpandedCats(prev => { const s = new Set(prev); s.has(cat.id) ? s.delete(cat.id) : s.add(cat.id); return s; })} className="text-gray-400">
                  {expandedCats.has(cat.id) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </button>
                <div className="w-3 h-3 rounded-full shrink-0" style={{ background: cat.color }} />
                <span className="text-sm font-semibold text-gray-900 dark:text-gray-100 flex-1">{cat.name}</span>
                <span className="text-xs text-gray-400 capitalize">{cat.type}</span>
                <button onClick={() => openNewCat(cat)} className="btn-ghost p-1 text-xs text-indigo-500" title="Add sub-category"><Plus size={12} /></button>
                <button onClick={() => openEditCat(cat)} className="btn-ghost p-1"><Pencil size={12} /></button>
                <button onClick={() => setDeleteCatId(cat.id)} className="btn-ghost p-1 text-red-400" disabled={cat.children?.length > 0}><Trash2 size={12} /></button>
              </div>
              {/* Sub-categories */}
              {expandedCats.has(cat.id) && cat.children?.map((ch: any) => (
                <div key={ch.id} className="flex items-center gap-2 py-1.5 pl-9 pr-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50">
                  <div className="w-2 h-2 rounded-full shrink-0" style={{ background: ch.color }} />
                  <span className="text-sm text-gray-700 dark:text-gray-300 flex-1">{ch.name}</span>
                  {/* Inline budget amount */}
                  {editBudgetCatId === ch.id ? (
                    <div className="flex items-center gap-1">
                      <input type="number" step="0.01" className="input w-24 py-0.5 text-right text-xs" value={budgetDraft} onChange={e => setBudgetDraft(e.target.value)} autoFocus />
                      <button onClick={() => saveBudget(ch.id)} className="text-green-600"><Check size={12} /></button>
                      <button onClick={() => setEditBudgetCatId(null)} className="text-gray-400"><X size={12} /></button>
                    </div>
                  ) : (
                    <button onClick={() => { setEditBudgetCatId(ch.id); setBudgetDraft(budgetMap[ch.id] ?? "0"); }} className="text-xs text-gray-500 dark:text-gray-400 hover:text-indigo-600 tabular-nums min-w-[4rem] text-right">
                      {budgetMap[ch.id] ? fmt(budgetMap[ch.id]) : "set budget"}
                    </button>
                  )}
                  <button onClick={() => openEditCat(ch)} className="btn-ghost p-1"><Pencil size={12} /></button>
                  <button onClick={() => setDeleteCatId(ch.id)} className="btn-ghost p-1 text-red-400"><Trash2 size={12} /></button>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* ── Users (admin only) ── */}
      {admin && (
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Shield size={16} className="text-indigo-500" />
              <h3 className="font-semibold text-gray-900 dark:text-gray-100">Users</h3>
            </div>
            <button onClick={() => setShowUserForm(true)} className="btn-primary btn-sm text-xs px-3 py-1.5"><Plus size={14} /> Add User</button>
          </div>
          <div className="divide-y divide-gray-100 dark:divide-gray-700">
            {users.map((u: any) => (
              <div key={u.id} className="py-3 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 bg-gray-100 dark:bg-gray-700 rounded-full flex items-center justify-center">
                    <User size={14} className="text-gray-500" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{u.display_name}</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">@{u.username}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`badge-${u.role === "admin" ? "blue" : "amber"}`}>{u.role}</span>
                  <button
                    onClick={() => updateUserMut.mutate({ id: u.id, data: { is_active: !u.is_active } })}
                    className={`text-xs px-2 py-1 rounded-md ${u.is_active ? "text-green-600 bg-green-50 dark:bg-green-900/20" : "text-gray-400 bg-gray-100 dark:bg-gray-700"}`}
                  >
                    {u.is_active ? "Active" : "Inactive"}
                  </button>
                  <select
                    className="input text-xs w-auto py-1"
                    value={u.role}
                    onChange={e => updateUserMut.mutate({ id: u.id, data: { role: e.target.value } })}
                  >
                    <option value="admin">Admin</option>
                    <option value="viewer">View Only</option>
                  </select>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Audit Log (admin only) ── */}
      {admin && (
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Activity size={16} className="text-indigo-500" />
              <h3 className="font-semibold text-gray-900 dark:text-gray-100">Activity Log</h3>
            </div>
            <div className="flex items-center gap-2">
              <select className="input text-xs w-auto py-1" value={logMethod} onChange={e => { setLogMethod(e.target.value); setLogPage(0); }}>
                <option value="">All methods</option>
                <option value="POST">POST</option>
                <option value="PATCH">PATCH</option>
                <option value="DELETE">DELETE</option>
              </select>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100 dark:border-gray-700">
                  <th className="text-left py-2 text-gray-500 font-medium pr-4">Time</th>
                  <th className="text-left py-2 text-gray-500 font-medium pr-4">User</th>
                  <th className="text-left py-2 text-gray-500 font-medium pr-4">Method</th>
                  <th className="text-left py-2 text-gray-500 font-medium pr-4">Path</th>
                  <th className="text-right py-2 text-gray-500 font-medium pr-4">Status</th>
                  <th className="text-right py-2 text-gray-500 font-medium">ms</th>
                </tr>
              </thead>
              <tbody>
                {(logData?.items ?? []).map((log: any) => (
                  <tr key={log.id} className="border-b border-gray-50 dark:border-gray-700/50 hover:bg-gray-50 dark:hover:bg-gray-700/30">
                    <td className="py-1.5 pr-4 text-gray-500 whitespace-nowrap">
                      {new Date(log.timestamp).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                    </td>
                    <td className="py-1.5 pr-4 text-gray-700 dark:text-gray-300">{log.username ?? "—"}</td>
                    <td className="py-1.5 pr-4">
                      <span className={`badge-${log.method === "DELETE" ? "red" : log.method === "PATCH" ? "amber" : "blue"}`}>{log.method}</span>
                    </td>
                    <td className="py-1.5 pr-4 text-gray-600 dark:text-gray-400 font-mono">{log.path}</td>
                    <td className="py-1.5 pr-4 text-right">
                      <span className={log.status_code < 300 ? "text-green-600" : log.status_code < 500 ? "text-amber-600" : "text-red-600"}>{log.status_code}</span>
                    </td>
                    <td className="py-1.5 text-right text-gray-500">{log.duration_ms}</td>
                  </tr>
                ))}
                {(!logData?.items?.length) && (
                  <tr><td colSpan={6} className="text-center py-6 text-gray-400">No activity yet</td></tr>
                )}
              </tbody>
            </table>
          </div>
          {logData && logData.total > 25 && (
            <div className="flex items-center justify-between mt-3 text-xs text-gray-500">
              <span>{logData.total} total entries</span>
              <div className="flex gap-2">
                <button onClick={() => setLogPage(p => Math.max(0, p - 1))} disabled={logPage === 0} className="btn-ghost px-2 py-1 text-xs disabled:opacity-40">← Prev</button>
                <span className="self-center">Page {logPage + 1}</span>
                <button onClick={() => setLogPage(p => p + 1)} disabled={(logPage + 1) * 25 >= logData.total} className="btn-ghost px-2 py-1 text-xs disabled:opacity-40">Next →</button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Add/Edit Account modal ── */}
      {showAccForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900 dark:text-gray-100">{editAcc ? "Edit Account" : "Add Account"}</h3>
              <button onClick={() => setShowAccForm(false)} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <form onSubmit={submitAcc} className="space-y-3">
              <div><label className="label">Name</label><input className="input" placeholder="Main Checking" value={accForm.name} onChange={e => setAccForm({ ...accForm, name: e.target.value })} required /></div>
              <div>
                <label className="label">Type</label>
                <select className="input" value={accForm.type} onChange={e => setAccForm({ ...accForm, type: e.target.value })}>
                  <option value="checking">Checking</option>
                  <option value="savings">Savings</option>
                  <option value="money_market">Money Market</option>
                </select>
              </div>
              <div><label className="label">Current Balance</label><input type="number" step="0.01" className="input" value={accForm.current_balance} onChange={e => setAccForm({ ...accForm, current_balance: e.target.value })} /></div>
              <div><label className="label">Warn When Balance Drops Below (optional)</label><input type="number" step="0.01" className="input" placeholder="e.g. 1000" value={accForm.low_balance_threshold} onChange={e => setAccForm({ ...accForm, low_balance_threshold: e.target.value })} /></div>
              <div><label className="label">Notes</label><input className="input" value={accForm.notes} onChange={e => setAccForm({ ...accForm, notes: e.target.value })} /></div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1">{editAcc ? "Save" : "Add"}</button>
                <button type="button" onClick={() => setShowAccForm(false)} className="btn-secondary flex-1">Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Delete account confirm ── */}
      {deleteAccId && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm text-center">
            <h3 className="font-bold text-gray-900 dark:text-gray-100 mb-1">Remove this account?</h3>
            <p className="text-sm text-gray-500 mb-5">It will be hidden but data is preserved.</p>
            <div className="flex gap-3">
              <button onClick={() => deleteAccMut.mutate(deleteAccId)} className="btn-danger flex-1">Remove</button>
              <button onClick={() => setDeleteAccId(null)} className="btn-secondary flex-1">Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Add/Edit Category modal ── */}
      {showCatForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900 dark:text-gray-100">{editCat ? "Edit Category" : "Add Category"}</h3>
              <button onClick={() => setShowCatForm(false)} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <form onSubmit={submitCat} className="space-y-3">
              <div><label className="label">Name</label><input className="input" placeholder="Food & Drinks" value={catForm.name} onChange={e => setCatForm({ ...catForm, name: e.target.value })} required /></div>
              <div>
                <label className="label">Type</label>
                <select className="input" value={catForm.type} onChange={e => setCatForm({ ...catForm, type: e.target.value })}>
                  <option value="expense">Expense</option>
                  <option value="income">Income</option>
                </select>
              </div>
              <div>
                <label className="label">Parent Category (leave empty for top-level)</label>
                <select className="input" value={catForm.parent_id} onChange={e => setCatForm({ ...catForm, parent_id: e.target.value })}>
                  <option value="">None (top-level)</option>
                  {categories.filter((c: any) => !c.parent_id).map((c: any) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Color</label>
                <div className="flex gap-2 flex-wrap">
                  {COLOR_SWATCHES.map(c => (
                    <button key={c} type="button" onClick={() => setCatForm({ ...catForm, color: c })}
                      className={`w-7 h-7 rounded-full border-2 transition-transform ${catForm.color === c ? "border-gray-900 dark:border-white scale-110" : "border-transparent"}`}
                      style={{ background: c }} />
                  ))}
                  <input type="color" className="w-7 h-7 rounded-full cursor-pointer border-0 p-0" value={catForm.color} onChange={e => setCatForm({ ...catForm, color: e.target.value })} />
                </div>
              </div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1">{editCat ? "Save" : "Add"}</button>
                <button type="button" onClick={() => setShowCatForm(false)} className="btn-secondary flex-1">Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Delete category confirm ── */}
      {deleteCatId && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm text-center">
            <h3 className="font-bold text-gray-900 dark:text-gray-100 mb-1">Delete this category?</h3>
            <p className="text-sm text-gray-500 mb-5">Transactions in this category will become uncategorized.</p>
            <div className="flex gap-3">
              <button onClick={() => deleteCatMut.mutate(deleteCatId)} className="btn-danger flex-1">Delete</button>
              <button onClick={() => setDeleteCatId(null)} className="btn-secondary flex-1">Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Add User modal ── */}
      {showUserForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900 dark:text-gray-100">Add User</h3>
              <button onClick={() => setShowUserForm(false)} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <form onSubmit={e => { e.preventDefault(); createUserMut.mutate(userForm); }} className="space-y-3">
              <div><label className="label">Display Name</label><input className="input" placeholder="Jane Ford" value={userForm.display_name} onChange={e => setUserForm({ ...userForm, display_name: e.target.value })} required /></div>
              <div><label className="label">Username</label><input className="input" placeholder="janeford" value={userForm.username} onChange={e => setUserForm({ ...userForm, username: e.target.value })} required /></div>
              <div><label className="label">Password</label><input type="password" className="input" value={userForm.password} onChange={e => setUserForm({ ...userForm, password: e.target.value })} required /></div>
              <div>
                <label className="label">Access Level</label>
                <select className="input" value={userForm.role} onChange={e => setUserForm({ ...userForm, role: e.target.value })}>
                  <option value="viewer">View Only</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1">Create User</button>
                <button type="button" onClick={() => setShowUserForm(false)} className="btn-secondary flex-1">Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

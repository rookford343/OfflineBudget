import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { categoriesApi, budgetApi, rulesApi } from "../../api";
import { fmt } from "../../lib/utils";
import { Plus, Pencil, Trash2, X, Check, ChevronRight, ChevronDown } from "lucide-react";

const emptyCat = { name: "", type: "expense", parent_id: "", color: "#6366f1", tax_deductible: false };
const COLOR_SWATCHES = ["#6366f1", "#22c55e", "#ef4444", "#f59e0b", "#3b82f6", "#8b5cf6", "#ec4899", "#14b8a6"];

export default function CategoriesTab() {
  const qc = useQueryClient();
  const currentYear = new Date().getFullYear();
  const { data: categories = [] } = useQuery<any[]>({ queryKey: ["categories"], queryFn: categoriesApi.list });
  const { data: budgets = [] } = useQuery<any[]>({ queryKey: ["budget", currentYear], queryFn: () => budgetApi.list(currentYear) });

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
    setCatForm({
      name: "",
      type: parentCat?.type ?? "expense",
      parent_id: parentCat?.id?.toString() ?? "",
      color: "#6366f1",
      tax_deductible: parentCat?.tax_deductible ?? false,
    });
    setEditCat(null);
    setShowCatForm(true);
  }
  function openEditCat(c: any) {
    setEditCat(c);
    setCatForm({ name: c.name, type: c.type, parent_id: c.parent_id?.toString() ?? "", color: c.color, tax_deductible: c.tax_deductible ?? false });
    setShowCatForm(true);
  }
  function saveBudget(catId: number) {
    upsertBudgetMut.mutate({ category_id: catId, year: currentYear, month: 0, budgeted_amount: parseFloat(budgetDraft) || 0 });
  }

  const { data: rules = [] } = useQuery<any[]>({ queryKey: ["rules"], queryFn: rulesApi.list });
  const emptyRule = { name: "", field: "description", pattern_type: "contains", pattern: "", action: "set_category", category_id: "", priority: "0" };
  const [showRuleForm, setShowRuleForm] = useState(false);
  const [editRule, setEditRule] = useState<any | null>(null);
  const [ruleForm, setRuleForm] = useState({ ...emptyRule });
  const [deleteRuleId, setDeleteRuleId] = useState<number | null>(null);
  const [ruleTestDesc, setRuleTestDesc] = useState("");
  const [ruleTestResult, setRuleTestResult] = useState<boolean | null>(null);
  const createRuleMut = useMutation({ mutationFn: rulesApi.create, onSuccess: () => { qc.invalidateQueries({ queryKey: ["rules"] }); setShowRuleForm(false); } });
  const updateRuleMut = useMutation({ mutationFn: ({ id, data }: any) => rulesApi.update(id, data), onSuccess: () => { qc.invalidateQueries({ queryKey: ["rules"] }); setEditRule(null); setShowRuleForm(false); } });
  const deleteRuleMut = useMutation({ mutationFn: rulesApi.remove, onSuccess: () => { qc.invalidateQueries({ queryKey: ["rules"] }); setDeleteRuleId(null); } });
  function submitRule(e: React.FormEvent) {
    e.preventDefault();
    const data = { ...ruleForm, priority: parseInt(ruleForm.priority) || 0, category_id: ruleForm.category_id ? parseInt(ruleForm.category_id) : null };
    if (editRule) updateRuleMut.mutate({ id: editRule.id, data });
    else createRuleMut.mutate(data);
  }
  function openEditRule(r: any) {
    setEditRule(r);
    setRuleForm({ name: r.name, field: r.field, pattern_type: r.pattern_type, pattern: r.pattern, action: r.action, category_id: r.category_id?.toString() ?? "", priority: r.priority.toString() });
    setRuleTestDesc(""); setRuleTestResult(null);
    setShowRuleForm(true);
  }
  function handleTestRule() {
    if (!ruleTestDesc || !ruleForm.pattern) return;
    rulesApi.test({ pattern: ruleForm.pattern, pattern_type: ruleForm.pattern_type, description: ruleTestDesc })
      .then((r: any) => setRuleTestResult(r.matched));
  }

  return (
    <div className="space-y-6">
      {/* ── Categories ── */}
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">Categories</h3>
          <button onClick={() => openNewCat()} className="btn-primary btn-sm text-xs px-3 py-1.5"><Plus size={14} /> Add Category</button>
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">Click a budget amount to edit it inline</p>
        <div className="space-y-1">
          {categories.map((cat: any) => (
            <div key={cat.id}>
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
              {expandedCats.has(cat.id) && cat.children?.map((ch: any) => (
                <div key={ch.id} className="flex items-center gap-2 py-1.5 pl-9 pr-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50">
                  <div className="w-2 h-2 rounded-full shrink-0" style={{ background: ch.color }} />
                  <span className="text-sm text-gray-700 dark:text-gray-300 flex-1">{ch.name}</span>
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

      {/* ── Transaction Rules ── */}
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">Transaction Rules</h3>
          <button onClick={() => { setEditRule(null); setRuleForm({ ...emptyRule }); setRuleTestDesc(""); setRuleTestResult(null); setShowRuleForm(true); }} className="btn-primary btn-sm text-xs px-3 py-1.5"><Plus size={14} /> Add Rule</button>
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">Auto-categorize transactions at import based on description patterns</p>
        {rules.length === 0 && <p className="text-sm text-gray-400 py-2">No rules yet. Add one to auto-categorize imports.</p>}
        {rules.length > 0 && (
          <div className="divide-y divide-gray-100 dark:divide-gray-700">
            {rules.map((r: any) => (
              <div key={r.id} className="py-2.5 flex items-center justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-gray-900 dark:text-gray-100">{r.name}</span>
                    {!r.is_active && <span className="text-xs text-gray-400 bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded">inactive</span>}
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                    {r.field} {r.pattern_type} <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">{r.pattern}</code>
                    {" → "}{r.action === "set_category" ? (categories.flatMap((c: any) => [c, ...(c.children ?? [])]).find((c: any) => c.id === r.category_id)?.name ?? "category") : "mark transfer"}
                  </p>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button onClick={() => openEditRule(r)} className="btn-ghost p-1"><Pencil size={14} /></button>
                  <button onClick={() => setDeleteRuleId(r.id)} className="btn-ghost p-1 text-red-400"><Trash2 size={14} /></button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

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
                  <option value="savings">Savings (excluded from spending totals)</option>
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
              {catForm.type === "expense" && (
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={catForm.tax_deductible}
                    onChange={e => setCatForm({ ...catForm, tax_deductible: e.target.checked })}
                    className="w-4 h-4 rounded accent-indigo-600"
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300">Tax deductible (include in Tax Export)</span>
                </label>
              )}
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

      {/* ── Add/Edit Rule modal ── */}
      {showRuleForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-md">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900 dark:text-gray-100">{editRule ? "Edit Rule" : "Add Rule"}</h3>
              <button onClick={() => setShowRuleForm(false)} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <form onSubmit={submitRule} className="space-y-3">
              <div><label className="label">Rule Name</label><input className="input" placeholder="e.g. Spotify → Subscriptions" value={ruleForm.name} onChange={e => setRuleForm({ ...ruleForm, name: e.target.value })} required /></div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Pattern Type</label>
                  <select className="input" value={ruleForm.pattern_type} onChange={e => { setRuleForm({ ...ruleForm, pattern_type: e.target.value }); setRuleTestResult(null); }}>
                    <option value="contains">Contains</option>
                    <option value="startswith">Starts with</option>
                    <option value="regex">Regex</option>
                  </select>
                </div>
                <div>
                  <label className="label">Priority (higher runs first)</label>
                  <input type="number" className="input" value={ruleForm.priority} onChange={e => setRuleForm({ ...ruleForm, priority: e.target.value })} />
                </div>
              </div>
              <div>
                <label className="label">Pattern</label>
                <input className="input font-mono" placeholder={ruleForm.pattern_type === "regex" ? "e.g. SPOTIFY|NETFLIX" : "e.g. SPOTIFY"} value={ruleForm.pattern} onChange={e => { setRuleForm({ ...ruleForm, pattern: e.target.value }); setRuleTestResult(null); }} required />
              </div>
              <div>
                <label className="label">Action</label>
                <select className="input" value={ruleForm.action} onChange={e => setRuleForm({ ...ruleForm, action: e.target.value })}>
                  <option value="set_category">Set Category</option>
                  <option value="mark_transfer">Mark as Transfer</option>
                </select>
              </div>
              {ruleForm.action === "set_category" && (
                <div>
                  <label className="label">Category</label>
                  <select className="input" value={ruleForm.category_id} onChange={e => setRuleForm({ ...ruleForm, category_id: e.target.value })} required>
                    <option value="">Select…</option>
                    {categories.flatMap((c: any) => [c, ...(c.children ?? [])]).map((c: any) => (
                      <option key={c.id} value={c.id}>{c.parent_id ? "  " : ""}{c.name}</option>
                    ))}
                  </select>
                </div>
              )}
              <div className="border-t border-gray-100 dark:border-gray-700 pt-3">
                <label className="label">Live Test</label>
                <div className="flex gap-2">
                  <input className="input flex-1 text-sm" placeholder="Paste a transaction description…" value={ruleTestDesc} onChange={e => { setRuleTestDesc(e.target.value); setRuleTestResult(null); }} />
                  <button type="button" onClick={handleTestRule} className="btn-secondary text-sm px-3 shrink-0">Test</button>
                </div>
                {ruleTestResult !== null && (
                  <p className={`text-xs mt-1 ${ruleTestResult ? "text-green-600" : "text-red-500"}`}>
                    {ruleTestResult ? "✓ Pattern matches" : "✗ No match"}
                  </p>
                )}
              </div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1">{editRule ? "Save" : "Add Rule"}</button>
                <button type="button" onClick={() => setShowRuleForm(false)} className="btn-secondary flex-1">Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Delete Rule confirm ── */}
      {deleteRuleId && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm text-center">
            <h3 className="font-bold text-gray-900 dark:text-gray-100 mb-1">Delete this rule?</h3>
            <p className="text-sm text-gray-500 mb-5">Future imports won't use this rule. Existing transactions are unaffected.</p>
            <div className="flex gap-3">
              <button onClick={() => deleteRuleMut.mutate(deleteRuleId)} className="btn-danger flex-1">Delete</button>
              <button onClick={() => setDeleteRuleId(null)} className="btn-secondary flex-1">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

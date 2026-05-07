import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { accountsApi, categoriesApi, budgetApi, adminApi, authApi, rulesApi, checkpointsApi, dataApi } from "../api";
import { fmt } from "../lib/utils";
import { getTheme, setTheme } from "../store/theme";
import { clearAuth, isAdmin } from "../store/auth";
import {
  Plus, Pencil, Trash2, X, Check, Moon, Sun, ChevronRight, ChevronDown, ChevronUp,
  AlertTriangle, Shield, User, Activity, KeyRound, Link, Mail, RotateCcw, Wand2
} from "lucide-react";
import HelpPanel from "../components/HelpPanel";

const emptyAccount = { name: "", type: "checking", current_balance: "0", low_balance_threshold: "", interest_rate: "", notes: "" };
const emptyCat = { name: "", type: "expense", parent_id: "", color: "#6366f1", tax_deductible: false };
const emptyUser = { username: "", display_name: "", password: "", role: "viewer", linked_to_user_id: "" };

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
  const { data: editBalCheckpoints = [] } = useQuery<any[]>({
    queryKey: ["checkpoints", editBalId],
    queryFn: () => checkpointsApi.list(editBalId!),
    enabled: editBalId !== null,
  });

  const createAccMut = useMutation({ mutationFn: accountsApi.create, onSuccess: () => { qc.invalidateQueries({ queryKey: ["accounts"] }); setShowAccForm(false); } });
  const updateAccMut = useMutation({ mutationFn: ({ id, data }: any) => accountsApi.update(id, data), onSuccess: () => { qc.invalidateQueries({ queryKey: ["accounts"] }); setEditAcc(null); setShowAccForm(false); setEditBalId(null); } });
  const deleteAccMut = useMutation({ mutationFn: accountsApi.remove, onSuccess: () => { qc.invalidateQueries({ queryKey: ["accounts"] }); setDeleteAccId(null); } });

  function submitAcc(e: React.FormEvent) {
    e.preventDefault();
    const data = {
      ...accForm,
      current_balance: parseFloat(accForm.current_balance),
      low_balance_threshold: accForm.low_balance_threshold ? parseFloat(accForm.low_balance_threshold) : null,
      interest_rate: accForm.interest_rate ? parseFloat(accForm.interest_rate) : null,
    };
    if (editAcc) updateAccMut.mutate({ id: editAcc.id, data });
    else createAccMut.mutate(data);
  }
  function openNewAcc() { setAccForm({ ...emptyAccount }); setEditAcc(null); setShowAccForm(true); }
  function openEditAcc(a: any) {
    setEditAcc(a);
    setAccForm({ name: a.name, type: a.type, current_balance: a.current_balance, low_balance_threshold: a.low_balance_threshold ?? "", interest_rate: a.interest_rate ?? "", notes: a.notes ?? "" });
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
    setCatForm({ name: c.name, type: c.type, parent_id: c.parent_id?.toString() ?? "", color: c.color, tax_deductible: c.tax_deductible ?? false });
    setShowCatForm(true);
  }
  function saveBudget(catId: number) {
    upsertBudgetMut.mutate({ category_id: catId, year: currentYear, month: 0, budgeted_amount: parseFloat(budgetDraft) || 0 });
  }

  // ── Dark mode ──────────────────────────────────────────────────────────────
  const [dark, setDark] = useState(getTheme() === "dark");
  function toggleDark() { const next = !dark; setDark(next); setTheme(next); }

  // ── Profile ────────────────────────────────────────────────────────────────
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: authApi.me });
  const [profileName, setProfileName] = useState("");
  const [profileSaved, setProfileSaved] = useState(false);
  const [pwForm, setPwForm] = useState({ current: "", next: "", confirm: "" });
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwSaved, setPwSaved] = useState(false);
  const [profileEmail, setProfileEmail] = useState("");
  const [testEmailStatus, setTestEmailStatus] = useState<"idle" | "sending" | "ok" | "err">("idle");
  // ── Tax profile state ─────────────────────────────────────────────────────
  const [taxFilingStatus, setTaxFilingStatus] = useState("single");
  const [taxState, setTaxState] = useState("");
  const [taxSalary, setTaxSalary] = useState("");
  const [taxOtherIncome, setTaxOtherIncome] = useState("");
  const [taxFedWithheld, setTaxFedWithheld] = useState("");
  const [taxStateWithheld, setTaxStateWithheld] = useState("");
  const [taxMortgageInterest, setTaxMortgageInterest] = useState("");
  const [taxDonations, setTaxDonations] = useState("");
  const [taxSalt, setTaxSalt] = useState("");
  const [taxPropertyTax, setTaxPropertyTax] = useState("");
  const [taxOther, setTaxOther] = useState("");
  const [taxSaved, setTaxSaved] = useState(false);
  const taxMut = useMutation({
    mutationFn: authApi.updateMe,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["me"] }); setTaxSaved(true); setTimeout(() => setTaxSaved(false), 2000); },
  });

  React.useEffect(() => {
    if (me) {
      setProfileName(me.display_name ?? "");
      setProfileEmail(me.email ?? "");
      setSsGross(me.ss_gross_per_paycheck ?? "");
      setSsWageBase(me.ss_wage_base ?? "176100");
      setSsBonus(me.ss_bonus_ytd ?? "");
      setTaxFilingStatus(me.tax_filing_status ?? "single");
      setTaxState(me.tax_state ?? "");
      setTaxSalary(me.annual_salary ?? "");
      setTaxOtherIncome(me.other_income ?? "");
      setTaxFedWithheld(me.federal_withholding_ytd ?? "");
      setTaxStateWithheld(me.state_withholding_ytd ?? "");
      setTaxMortgageInterest(me.itemized_mortgage_interest ?? "");
      setTaxDonations(me.itemized_donations ?? "");
      setTaxSalt(me.itemized_salt ?? "");
      setTaxPropertyTax(me.itemized_property_tax ?? "");
      setTaxOther(me.itemized_other ?? "");
    }
  }, [me]);
  const updateMeMut = useMutation({
    mutationFn: authApi.updateMe,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["me"] }); setProfileSaved(true); setTimeout(() => setProfileSaved(false), 2000); },
  });
  const sendTestEmailMut = useMutation({
    mutationFn: authApi.sendTestEmail,
    onMutate: () => setTestEmailStatus("sending"),
    onSuccess: () => { setTestEmailStatus("ok"); setTimeout(() => setTestEmailStatus("idle"), 3000); },
    onError: () => { setTestEmailStatus("err"); setTimeout(() => setTestEmailStatus("idle"), 3000); },
  });
  const changePasswordMut = useMutation({
    mutationFn: authApi.changePassword,
    onSuccess: () => { setPwForm({ current: "", next: "", confirm: "" }); setPwError(null); setPwSaved(true); setTimeout(() => setPwSaved(false), 2000); },
    onError: (e: any) => setPwError(e?.response?.data?.detail ?? "Failed to change password"),
  });
  function submitPassword(e: React.FormEvent) {
    e.preventDefault();
    if (pwForm.next !== pwForm.confirm) { setPwError("New passwords don't match"); return; }
    if (pwForm.next.length < 6) { setPwError("Password must be at least 6 characters"); return; }
    setPwError(null);
    changePasswordMut.mutate({ current_password: pwForm.current, new_password: pwForm.next });
  }

  // ── Social Security ────────────────────────────────────────────────────────
  const [ssGross, setSsGross] = useState("");
  const [ssWageBase, setSsWageBase] = useState("");
  const [ssBonus, setSsBonus] = useState("");

  // ── Nav order ─────────────────────────────────────────────────────────────
  const ALL_NAV_ITEMS = [
    { to: "/dashboard", label: "Dashboard" },
    { to: "/goals", label: "Goals" },
    { to: "/net-worth", label: "Net Worth" },
    { to: "/calendar", label: "Calendar" },
    { to: "/credit-cards", label: "Credit Cards" },
    { to: "/forecast", label: "Forecast" },
    { to: "/spending", label: "Spending" },
    { to: "/recurring", label: "Recurring" },
    { to: "/transactions", label: "Transactions" },
    { to: "/import", label: "Import" },
    { to: "/budget", label: "Budget" },
    { to: "/settings", label: "Settings" },
  ];
  const defaultNavOrder = ALL_NAV_ITEMS.map(n => n.to);
  const [navOrder, setNavOrder] = useState<string[]>(() => {
    try {
      const saved = localStorage.getItem("navOrder");
      return saved ? JSON.parse(saved) : defaultNavOrder;
    } catch { return defaultNavOrder; }
  });
  const navItems = navOrder.map(to => ALL_NAV_ITEMS.find(n => n.to === to)!).filter(Boolean);
  function moveNav(index: number, dir: -1 | 1) {
    const next = [...navOrder];
    const target = index + dir;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setNavOrder(next);
    localStorage.setItem("navOrder", JSON.stringify(next));
    window.dispatchEvent(new CustomEvent("nav-order-changed"));
  }
  function resetNavOrder() {
    setNavOrder(defaultNavOrder);
    localStorage.removeItem("navOrder");
    window.dispatchEvent(new CustomEvent("nav-order-changed"));
  }

  // ── Transaction Rules ──────────────────────────────────────────────────────
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

  // ── Accordion ─────────────────────────────────────────────────────────────
  const [openSections, setOpenSections] = useState<Set<string>>(
    () => new Set(["preferences", "accounts"])
  );
  function toggleSection(key: string) {
    setOpenSections(s => { const next = new Set(s); next.has(key) ? next.delete(key) : next.add(key); return next; });
  }

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const deleteAccountMut = useMutation({
    mutationFn: authApi.deleteAccount,
    onSuccess: () => { clearAuth(); window.location.href = "/login"; },
    onError: (e: any) => setDeleteError(e?.response?.data?.detail ?? "Failed to delete account"),
  });
  function handleDeleteAccount() { setDeleteError(null); deleteAccountMut.mutate({ password: deletePassword }); }

  const [clearConfirm, setClearConfirm] = useState<"transactions" | "cc-transactions" | null>(null);
  const clearTxnMut = useMutation({
    mutationFn: dataApi.clearTransactions,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      setClearConfirm(null);
    },
  });
  const clearCCTxnMut = useMutation({
    mutationFn: dataApi.clearCCTransactions,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cc-transactions"] });
      qc.invalidateQueries({ queryKey: ["credit-cards"] });
      setClearConfirm(null);
    },
  });

  // ── User management ────────────────────────────────────────────────────────
  const [showUserForm, setShowUserForm] = useState(false);
  const [userForm, setUserForm] = useState({ ...emptyUser });
  const [resetPwUserId, setResetPwUserId] = useState<number | null>(null);
  const [resetPwValue, setResetPwValue] = useState("");
  const [resetPwError, setResetPwError] = useState<string | null>(null);
  const createUserMut = useMutation({ mutationFn: adminApi.createUser, onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin-users"] }); setShowUserForm(false); setUserForm({ ...emptyUser }); } });
  const updateUserMut = useMutation({ mutationFn: ({ id, data }: any) => adminApi.updateUser(id, data), onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin-users"] }); } });
  const removeUserMut = useMutation({ mutationFn: adminApi.removeUser, onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }) });
  const resetPwMut = useMutation({
    mutationFn: ({ id, pw }: { id: number; pw: string }) => adminApi.resetPassword(id, pw),
    onSuccess: () => { setResetPwUserId(null); setResetPwValue(""); setResetPwError(null); },
    onError: (e: any) => setResetPwError(e?.response?.data?.detail ?? "Failed to reset password"),
  });

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">Settings</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">Manage accounts, categories, and preferences</p>
      </div>

      {/* ── Preferences ── */}
      <div className="card">
        <button onClick={() => toggleSection("preferences")} className="w-full flex items-center justify-between">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">Preferences</h3>
          <ChevronDown size={16} className={`text-gray-400 transition-transform ${openSections.has("preferences") ? "" : "-rotate-90"}`} />
        </button>
        {openSections.has("preferences") && <div className="mt-4">
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
        <div className="flex items-center justify-between py-2 border-t border-gray-100 dark:border-gray-700">
          <div className="flex items-center gap-3">
            <Wand2 size={16} className="text-indigo-400" />
            <div>
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Setup Wizard</span>
              <p className="text-xs text-gray-400">Add an account and income recurring item</p>
            </div>
          </div>
          <button
            onClick={() => window.dispatchEvent(new Event("open-wizard"))}
            className="btn-secondary text-sm px-3 py-1.5"
          >
            Open
          </button>
        </div>
        <div className="pt-3 border-t border-gray-100 dark:border-gray-700">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Navigation Order</span>
            <button onClick={resetNavOrder} className="text-xs text-gray-400 hover:text-indigo-500">Reset</button>
          </div>
          <div className="space-y-1">
            {navItems.map((item, i) => (
              <div key={item.to} className="flex items-center gap-2 py-1 px-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50">
                <span className="text-sm text-gray-700 dark:text-gray-300 flex-1">{item.label}</span>
                <button onClick={() => moveNav(i, -1)} disabled={i === 0} className="btn-ghost p-1 disabled:opacity-30"><ChevronUp size={12} /></button>
                <button onClick={() => moveNav(i, 1)} disabled={i === navItems.length - 1} className="btn-ghost p-1 disabled:opacity-30"><ChevronDown size={12} /></button>
              </div>
            ))}
          </div>
        </div>
        </div>}
      </div>

      {/* ── Accounts ── */}
      <div className="card">
        <div className="flex items-center justify-between">
          <button onClick={() => toggleSection("accounts")} className="flex items-center gap-2 flex-1 text-left">
            <h3 className="font-semibold text-gray-900 dark:text-gray-100">Accounts</h3>
            <ChevronDown size={16} className={`ml-1 text-gray-400 transition-transform ${openSections.has("accounts") ? "" : "-rotate-90"}`} />
          </button>
          {openSections.has("accounts") && <button onClick={openNewAcc} className="btn-primary btn-sm text-xs px-3 py-1.5"><Plus size={14} /> Add Account</button>}
        </div>
        {openSections.has("accounts") && <div className="mt-4">
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
                  <div className="flex flex-col items-end gap-1">
                    <div className="flex items-center gap-1">
                      <input type="number" step="0.01" className="input w-28 py-1 text-right" value={newBal} onChange={e => setNewBal(e.target.value)} autoFocus />
                      <button onClick={() => updateAccMut.mutate({ id: a.id, data: { current_balance: parseFloat(newBal) } })} className="text-green-600"><Check size={14} /></button>
                      <button onClick={() => setEditBalId(null)} className="text-gray-400"><X size={14} /></button>
                    </div>
                    {editBalCheckpoints.length > 0 && (() => {
                      const latest = [...editBalCheckpoints].sort((a: any, b: any) => b.year !== a.year ? b.year - a.year : b.quarter - a.quarter)[0];
                      return (
                        <button onClick={() => setNewBal(String(latest.actual_balance))} className="text-xs text-indigo-500 hover:text-indigo-700">
                          Use Q{latest.quarter} {latest.year} checkpoint: {fmt(latest.actual_balance)}
                        </button>
                      );
                    })()}
                  </div>
                ) : (
                  <button onClick={() => { setEditBalId(a.id); setNewBal(a.current_balance); }} className="text-sm font-bold text-gray-900 dark:text-gray-100 tabular-nums hover:text-indigo-600 transition-colors" title="Click to correct balance">
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
        </div>}
      </div>

      {/* ── Categories ── */}
      <div className="card">
        <div className="flex items-center justify-between">
          <button onClick={() => toggleSection("categories")} className="flex items-center gap-2 flex-1 text-left">
            <h3 className="font-semibold text-gray-900 dark:text-gray-100">Categories</h3>
            <ChevronDown size={16} className={`ml-1 text-gray-400 transition-transform ${openSections.has("categories") ? "" : "-rotate-90"}`} />
          </button>
          {openSections.has("categories") && <button onClick={() => openNewCat()} className="btn-primary btn-sm text-xs px-3 py-1.5"><Plus size={14} /> Add Category</button>}
        </div>
        {openSections.has("categories") && <div className="mt-4">
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">Click a budget amount to edit it inline</p>
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
        </div>}
      </div>

      {/* ── Transaction Rules ── */}
      <div className="card">
        <div className="flex items-center justify-between">
          <button onClick={() => toggleSection("rules")} className="flex items-center gap-2 flex-1 text-left">
            <h3 className="font-semibold text-gray-900 dark:text-gray-100">Transaction Rules</h3>
            <ChevronDown size={16} className={`ml-1 text-gray-400 transition-transform ${openSections.has("rules") ? "" : "-rotate-90"}`} />
          </button>
          {openSections.has("rules") && <button onClick={() => { setEditRule(null); setRuleForm({ ...emptyRule }); setRuleTestDesc(""); setRuleTestResult(null); setShowRuleForm(true); }} className="btn-primary btn-sm text-xs px-3 py-1.5"><Plus size={14} /> Add Rule</button>}
        </div>
        {openSections.has("rules") && <div className="mt-4">
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
        </div>}
      </div>

      {/* ── Users (admin only) ── */}
      {admin && (
        <div className="card">
          <div className="flex items-center justify-between">
            <button onClick={() => toggleSection("users")} className="flex items-center gap-2 flex-1 text-left">
              <Shield size={16} className="text-indigo-500" />
              <h3 className="font-semibold text-gray-900 dark:text-gray-100">Users</h3>
              <ChevronDown size={16} className={`ml-1 text-gray-400 transition-transform ${openSections.has("users") ? "" : "-rotate-90"}`} />
            </button>
            {openSections.has("users") && <button onClick={() => setShowUserForm(true)} className="btn-primary btn-sm text-xs px-3 py-1.5"><Plus size={14} /> Add User</button>}
          </div>
          {openSections.has("users") && <div className="mt-4">
          <div className="divide-y divide-gray-100 dark:divide-gray-700">
            {users.map((u: any) => {
              const linkedTo = u.linked_to_user_id ? users.find((x: any) => x.id === u.linked_to_user_id) : null;
              return (
                <div key={u.id} className="py-3 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 bg-gray-100 dark:bg-gray-700 rounded-full flex items-center justify-center">
                      {linkedTo ? <Link size={14} className="text-indigo-500" /> : <User size={14} className="text-gray-500" />}
                    </div>
                    <div>
                      <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{u.display_name}</p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">@{u.username}</p>
                      {linkedTo && (
                        <p className="text-xs text-indigo-500 dark:text-indigo-400">Linked to {linkedTo.display_name}'s data</p>
                      )}
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
                    <button
                      onClick={() => { setResetPwUserId(u.id); setResetPwValue(""); setResetPwError(null); }}
                      className="btn-ghost p-1.5 text-amber-500 hover:bg-amber-50 dark:hover:bg-amber-900/20"
                      title="Reset password"
                    >
                      <RotateCcw size={14} />
                    </button>
                    {u.id !== me?.id && (
                      <button
                        onClick={() => removeUserMut.mutate(u.id)}
                        className="btn-ghost p-1.5 text-red-400 hover:bg-red-50"
                        title="Remove user"
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          </div>}
        </div>
      )}

      {/* ── Audit Log (admin only) ── */}
      {admin && (
        <div className="card">
          <div className="flex items-center justify-between">
            <button onClick={() => toggleSection("auditlog")} className="flex items-center gap-2 flex-1 text-left">
              <Activity size={16} className="text-indigo-500" />
              <h3 className="font-semibold text-gray-900 dark:text-gray-100">Activity Log</h3>
              <ChevronDown size={16} className={`ml-1 text-gray-400 transition-transform ${openSections.has("auditlog") ? "" : "-rotate-90"}`} />
            </button>
            {openSections.has("auditlog") && <div className="flex items-center gap-2">
              <select className="input text-xs w-auto py-1" value={logMethod} onChange={e => { setLogMethod(e.target.value); setLogPage(0); }}>
                <option value="">All methods</option>
                <option value="POST">POST</option>
                <option value="PATCH">PATCH</option>
                <option value="DELETE">DELETE</option>
              </select>
            </div>}
          </div>
          {openSections.has("auditlog") && <div className="mt-4">
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
          </div>}
        </div>
      )}

      {/* ── Profile ── */}
      <div className="card">
        <button onClick={() => toggleSection("profile")} className="w-full flex items-center justify-between">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2"><User size={16} className="text-indigo-500" /> Profile</h3>
          <ChevronDown size={16} className={`text-gray-400 transition-transform ${openSections.has("profile") ? "" : "-rotate-90"}`} />
        </button>
        {openSections.has("profile") && <div className="mt-4 space-y-5">
        <div className="flex items-end gap-3">
          <div className="flex-1 max-w-xs">
            <label className="label">Display Name</label>
            <input className="input" value={profileName} onChange={e => setProfileName(e.target.value)} placeholder="Your name" />
          </div>
          <button
            onClick={() => updateMeMut.mutate({ display_name: profileName })}
            disabled={updateMeMut.isPending || !profileName.trim()}
            className="btn-primary text-sm"
          >
            {updateMeMut.isPending ? "Saving…" : "Save"}
          </button>
          {profileSaved && <span className="text-sm text-green-600">Saved!</span>}
        </div>
        <div className="space-y-2">
          <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-2"><Mail size={14} /> Email Notifications</h4>
          <p className="text-xs text-gray-500 dark:text-gray-400">Used for daily summary emails. Requires SMTP to be configured on the server.</p>
          <div className="flex items-end gap-3">
            <div className="flex-1 max-w-xs">
              <label className="label">Email Address</label>
              <input type="email" className="input" value={profileEmail} onChange={e => setProfileEmail(e.target.value)} placeholder="you@example.com" />
            </div>
            <button
              onClick={() => updateMeMut.mutate({ email: profileEmail || null })}
              disabled={updateMeMut.isPending}
              className="btn-primary text-sm"
            >
              Save
            </button>
            <button
              onClick={() => sendTestEmailMut.mutate()}
              disabled={sendTestEmailMut.isPending || !me?.email}
              className="btn-secondary text-sm"
              title={!me?.email ? "Save an email address first" : "Send a test email"}
            >
              {testEmailStatus === "sending" ? "Sending…" : testEmailStatus === "ok" ? "Sent!" : testEmailStatus === "err" ? "Failed" : "Test"}
            </button>
          </div>
        </div>
        {/* Tax Profile */}
        <div className="space-y-3 border-t border-gray-100 dark:border-gray-700 pt-4">
          <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Tax Profile</h4>
          <p className="text-xs text-gray-500 dark:text-gray-400">Used to estimate your tax obligation in the Spending → Tax tab. All values are estimates — consult a tax professional.</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-xl">
            <div>
              <label className="label">Filing Status</label>
              <select className="input" value={taxFilingStatus} onChange={e => setTaxFilingStatus(e.target.value)}>
                <option value="single">Single</option>
                <option value="married_jointly">Married Filing Jointly</option>
                <option value="married_separately">Married Filing Separately</option>
                <option value="head_of_household">Head of Household</option>
              </select>
            </div>
            <div>
              <label className="label">State (2-letter code)</label>
              <input className="input uppercase" placeholder="e.g. TX" maxLength={2} value={taxState} onChange={e => setTaxState(e.target.value.toUpperCase())} />
            </div>
            <div>
              <label className="label">Annual Gross Salary (W-2)</label>
              <input type="number" step="1" className="input" placeholder="e.g. 85000" value={taxSalary} onChange={e => setTaxSalary(e.target.value)} />
            </div>
            <div>
              <label className="label">Other Income (1099, dividends, etc.)</label>
              <input type="number" step="1" className="input" placeholder="e.g. 5000" value={taxOtherIncome} onChange={e => setTaxOtherIncome(e.target.value)} />
            </div>
            <div>
              <label className="label">Federal Tax Withheld YTD</label>
              <input type="number" step="1" className="input" placeholder="From your pay stubs" value={taxFedWithheld} onChange={e => setTaxFedWithheld(e.target.value)} />
            </div>
            <div>
              <label className="label">State Tax Withheld YTD</label>
              <input type="number" step="1" className="input" placeholder="From your pay stubs" value={taxStateWithheld} onChange={e => setTaxStateWithheld(e.target.value)} />
            </div>
          </div>
          <div className="border-t border-gray-100 dark:border-gray-700 pt-3">
            <p className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">Itemized Deductions (from tax documents)</p>
            <p className="text-xs text-gray-400 dark:text-gray-500 mb-3">These are added to any transactions marked tax-deductible. If the total exceeds the standard deduction, itemized will be used automatically.</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-xl">
              <div>
                <label className="label">Mortgage Interest (Form 1098)</label>
                <input type="number" step="0.01" className="input" placeholder="e.g. 35919.55" value={taxMortgageInterest} onChange={e => setTaxMortgageInterest(e.target.value)} />
              </div>
              <div>
                <label className="label">Charitable Donations</label>
                <input type="number" step="0.01" className="input" placeholder="e.g. 15600.00" value={taxDonations} onChange={e => setTaxDonations(e.target.value)} />
              </div>
              <div>
                <label className="label">State &amp; Local Taxes (SALT)</label>
                <input type="number" step="0.01" className="input" placeholder="e.g. 10506.24" value={taxSalt} onChange={e => setTaxSalt(e.target.value)} />
              </div>
              <div>
                <label className="label">Property Taxes</label>
                <input type="number" step="0.01" className="input" placeholder="e.g. 6000.00" value={taxPropertyTax} onChange={e => setTaxPropertyTax(e.target.value)} />
              </div>
              <div>
                <label className="label">Other Deductions (vehicle tax, etc.)</label>
                <input type="number" step="0.01" className="input" placeholder="e.g. 713.00" value={taxOther} onChange={e => setTaxOther(e.target.value)} />
              </div>
            </div>
          </div>
          <div className="border-t border-gray-100 dark:border-gray-700 pt-3">
            <div className="flex items-center gap-2 mb-1">
              <p className="text-xs font-medium text-gray-600 dark:text-gray-400">Social Security Tracker</p>
            </div>
            <p className="text-xs text-gray-400 dark:text-gray-500 mb-3">Track when you hit the SS wage base to plan for your resulting paycheck increase (~6.2% of gross). The 2025 wage base is $176,100.</p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 max-w-xl">
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
          </div>
          <div className="flex items-center gap-3">
            <button
              className="btn-primary text-sm"
              disabled={taxMut.isPending}
              onClick={() => taxMut.mutate({
                tax_filing_status: taxFilingStatus,
                tax_state: taxState || null,
                annual_salary: taxSalary ? parseFloat(taxSalary) : null,
                other_income: taxOtherIncome ? parseFloat(taxOtherIncome) : null,
                federal_withholding_ytd: taxFedWithheld ? parseFloat(taxFedWithheld) : null,
                state_withholding_ytd: taxStateWithheld ? parseFloat(taxStateWithheld) : null,
                itemized_mortgage_interest: taxMortgageInterest ? parseFloat(taxMortgageInterest) : null,
                itemized_donations: taxDonations ? parseFloat(taxDonations) : null,
                itemized_salt: taxSalt ? parseFloat(taxSalt) : null,
                itemized_property_tax: taxPropertyTax ? parseFloat(taxPropertyTax) : null,
                itemized_other: taxOther ? parseFloat(taxOther) : null,
                ss_gross_per_paycheck: ssGross ? parseFloat(ssGross) : null,
                ss_wage_base: ssWageBase ? parseFloat(ssWageBase) : null,
                ss_bonus_ytd: ssBonus ? parseFloat(ssBonus) : null,
              })}
            >
              {taxMut.isPending ? "Saving…" : "Save Tax Profile"}
            </button>
            {taxSaved && <span className="text-sm text-green-600">Saved!</span>}
          </div>
        </div>

        <form onSubmit={submitPassword} className="space-y-3 border-t border-gray-100 dark:border-gray-700 pt-4">
          <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-2"><KeyRound size={14} /> Change Password</h4>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 max-w-xl">
            <div>
              <label className="label">Current Password</label>
              <input type="password" className="input" value={pwForm.current} onChange={e => setPwForm({ ...pwForm, current: e.target.value })} required />
            </div>
            <div>
              <label className="label">New Password</label>
              <input type="password" className="input" value={pwForm.next} onChange={e => setPwForm({ ...pwForm, next: e.target.value })} required />
            </div>
            <div>
              <label className="label">Confirm New Password</label>
              <input type="password" className="input" value={pwForm.confirm} onChange={e => setPwForm({ ...pwForm, confirm: e.target.value })} required />
            </div>
          </div>
          {pwError && <p className="text-sm text-red-600">{pwError}</p>}
          {pwSaved && <p className="text-sm text-green-600">Password changed!</p>}
          <button type="submit" disabled={changePasswordMut.isPending} className="btn-primary text-sm">
            {changePasswordMut.isPending ? "Updating…" : "Update Password"}
          </button>
        </form>
        </div>}
      </div>

      {/* ── Danger Zone ── */}
      <div className="card border-red-100 dark:border-red-900/30">
        <button onClick={() => toggleSection("danger")} className="w-full flex items-center justify-between">
          <h3 className="text-sm font-semibold text-red-600 dark:text-red-400">Danger Zone</h3>
          <ChevronDown size={16} className={`text-red-400 transition-transform ${openSections.has("danger") ? "" : "-rotate-90"}`} />
        </button>
        {openSections.has("danger") && <div className="mt-3 space-y-4">

          {/* Clear checking transactions */}
          <div className="border border-red-100 dark:border-red-900/30 rounded-lg p-3 space-y-2">
            {clearConfirm !== "transactions" ? (
              <button onClick={() => { setClearConfirm("transactions"); setShowDeleteConfirm(false); }} className="text-sm text-red-600 hover:underline">
                Clear all checking transactions…
              </button>
            ) : (
              <div className="space-y-2">
                <p className="text-xs text-red-600">This permanently deletes all checking transactions and resets all account balances to $0. Your accounts, categories, and settings are kept.</p>
                <div className="flex gap-2">
                  <button onClick={() => clearTxnMut.mutate()} disabled={clearTxnMut.isPending} className="bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-xs px-3 py-1.5 rounded-lg font-medium">
                    {clearTxnMut.isPending ? "Clearing…" : "Yes, clear transactions"}
                  </button>
                  <button onClick={() => setClearConfirm(null)} className="btn-secondary text-xs px-3">Cancel</button>
                </div>
              </div>
            )}
            <p className="text-xs text-gray-400">Keeps accounts, categories, recurring items, and rules.</p>
          </div>

          {/* Clear CC transactions */}
          <div className="border border-red-100 dark:border-red-900/30 rounded-lg p-3 space-y-2">
            {clearConfirm !== "cc-transactions" ? (
              <button onClick={() => { setClearConfirm("cc-transactions"); setShowDeleteConfirm(false); }} className="text-sm text-red-600 hover:underline">
                Clear all credit card transactions…
              </button>
            ) : (
              <div className="space-y-2">
                <p className="text-xs text-red-600">This permanently deletes all credit card transactions and resets all card balances to $0. Your cards, categories, and settings are kept.</p>
                <div className="flex gap-2">
                  <button onClick={() => clearCCTxnMut.mutate()} disabled={clearCCTxnMut.isPending} className="bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-xs px-3 py-1.5 rounded-lg font-medium">
                    {clearCCTxnMut.isPending ? "Clearing…" : "Yes, clear CC transactions"}
                  </button>
                  <button onClick={() => setClearConfirm(null)} className="btn-secondary text-xs px-3">Cancel</button>
                </div>
              </div>
            )}
            <p className="text-xs text-gray-400">Keeps cards, categories, recurring items, and rules.</p>
          </div>

          {/* Delete entire account */}
          <div className="border border-red-100 dark:border-red-900/30 rounded-lg p-3 space-y-2">
          {!showDeleteConfirm ? (
            <button onClick={() => { setShowDeleteConfirm(true); setClearConfirm(null); }} className="text-sm text-red-600 hover:underline">
              Delete my account and all data…
            </button>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-red-600">This permanently deletes all your accounts, transactions, and settings. Enter your password to confirm.</p>
              <div className="flex flex-wrap items-center gap-2 max-w-sm">
                <input type="password" className="input text-sm flex-1 min-w-0" placeholder="Your password" value={deletePassword} onChange={e => setDeletePassword(e.target.value)} />
                <button onClick={handleDeleteAccount} disabled={deleteAccountMut.isPending || !deletePassword} className="bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-sm px-3 py-2 rounded-lg font-medium">
                  {deleteAccountMut.isPending ? "Deleting…" : "Delete"}
                </button>
                <button onClick={() => { setShowDeleteConfirm(false); setDeletePassword(""); setDeleteError(null); }} className="btn-secondary text-sm px-3">Cancel</button>
              </div>
              {deleteError && <p className="text-xs text-red-600">{deleteError}</p>}
            </div>
          )}
          <p className="text-xs text-gray-400">Permanently removes your login, all accounts, and every piece of data.</p>
          </div>

        </div>}
      </div>

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
              <div><label className="label">Annual Interest Rate % (optional, for savings/HYSA)</label><input type="number" step="0.01" className="input" placeholder="e.g. 4.5" value={accForm.interest_rate} onChange={e => setAccForm({ ...accForm, interest_rate: e.target.value })} /></div>
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

      {/* ── Reset Password modal ── */}
      {resetPwUserId !== null && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900 dark:text-gray-100">Reset Password</h3>
              <button onClick={() => { setResetPwUserId(null); setResetPwValue(""); setResetPwError(null); }} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
              Set a new password for <strong>{users.find((u: any) => u.id === resetPwUserId)?.display_name ?? "this user"}</strong>. They will be able to change it again after logging in.
            </p>
            <div className="space-y-3">
              <div>
                <label className="label">New Password</label>
                <input
                  type="password"
                  className="input"
                  value={resetPwValue}
                  onChange={e => setResetPwValue(e.target.value)}
                  placeholder="At least 6 characters"
                  autoFocus
                />
              </div>
              {resetPwError && <p className="text-sm text-red-600">{resetPwError}</p>}
              <div className="flex gap-3 pt-2">
                <button
                  onClick={() => resetPwMut.mutate({ id: resetPwUserId, pw: resetPwValue })}
                  disabled={resetPwMut.isPending || resetPwValue.length < 6}
                  className="btn-primary flex-1"
                >
                  {resetPwMut.isPending ? "Saving…" : "Set Password"}
                </button>
                <button onClick={() => { setResetPwUserId(null); setResetPwValue(""); setResetPwError(null); }} className="btn-secondary flex-1">Cancel</button>
              </div>
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

      {/* ── Add User modal ── */}
      {showUserForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900 dark:text-gray-100">Add User</h3>
              <button onClick={() => setShowUserForm(false)} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <form onSubmit={e => {
              e.preventDefault();
              createUserMut.mutate({
                ...userForm,
                linked_to_user_id: userForm.linked_to_user_id ? parseInt(userForm.linked_to_user_id) : null,
              });
            }} className="space-y-3">
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
              <div>
                <label className="label">Link to Account (shared data access)</label>
                <select className="input" value={userForm.linked_to_user_id} onChange={e => setUserForm({ ...userForm, linked_to_user_id: e.target.value })}>
                  <option value="">Own account (standalone)</option>
                  <option value={String(me?.id)}>Link to my account ({me?.display_name})</option>
                </select>
                <p className="text-xs text-gray-400 mt-1">Linked users see the same financial data as your account.</p>
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

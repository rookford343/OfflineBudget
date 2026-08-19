import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { budgetApi, categoriesApi } from "../api";
import { fmt } from "../lib/utils";
import { Pencil, Check, X, RotateCcw, HelpCircle, ChevronRight, ChevronDown, Plus, Trash2 } from "lucide-react";
import HelpPanel from "../components/HelpPanel";

/**
 * Reworked 2026-08-16 around how Dan actually budgets: a handful of
 * top-level lines (Subscriptions $800, Shopping $1,500) that are easier to
 * hit than a dozen sub-limits, each expanding to show the merchants that add
 * up to it. Individual subscriptions aren't categories -- they're merchants
 * -- so the breakdown comes from /budget/category-breakdown rather than from
 * child rows.
 *
 * The previous version rolled child budgets up into their parent and showed
 * a fixed category tree with no way to add or remove a budget line. Deciding
 * what to budget meant leaving for the Spending page to look up what you'd
 * actually spent, so unbudgeted spend is now surfaced here with its own
 * amount as the suggested starting budget.
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function barColor(pct: number): string {
  if (pct >= 100) return "bg-red-500";
  if (pct >= 80) return "bg-amber-500";
  return "bg-emerald-500";
}

interface RowShape {
  category_id: number;
  category_name: string;
  budgeted: string;
  rollover_enabled?: boolean;
  rollover_balance?: string;
  actual_checking: string;
  actual_cards: string;
  actual_total: string;
  parent_id?: number | null;
  category_type?: string;
}

export default function Budget() {
  const now = new Date();
  const [showHelp, setShowHelp] = useState(false);
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [editId, setEditId] = useState<number | null>(null);
  const [editAmt, setEditAmt] = useState("");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [adding, setAdding] = useState(false);
  const [addCat, setAddCat] = useState("");
  const [addAmt, setAddAmt] = useState("");
  const qc = useQueryClient();

  const { data: overview = [], isLoading } = useQuery<RowShape[]>({
    queryKey: ["budget-overview", year, month],
    queryFn: () => budgetApi.overview(year, month),
  });
  // Allocations carry the id that DELETE needs; the overview is keyed by
  // category and has no way to name the row being removed.
  const { data: allocations = [] } = useQuery<any[]>({
    queryKey: ["budget-allocations", year],
    queryFn: () => budgetApi.list(year),
  });
  const { data: categories = [] } = useQuery<any[]>({
    queryKey: ["categories"],
    queryFn: categoriesApi.list,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["budget-overview"] });
    qc.invalidateQueries({ queryKey: ["budget-allocations"] });
  };

  const upsertMut = useMutation({
    mutationFn: budgetApi.upsert,
    onSuccess: () => { invalidate(); setEditId(null); setAdding(false); setAddCat(""); setAddAmt(""); },
  });
  const deleteMut = useMutation({
    mutationFn: budgetApi.remove,
    onSuccess: invalidate,
  });
  const rolloverToggleMut = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => budgetApi.setCategoryRollover(id, enabled),
    onSuccess: invalidate,
  });
  const applyRolloverMut = useMutation({
    mutationFn: () => {
      const prevMonth = month === 1 ? 12 : month - 1;
      const prevYear = month === 1 ? year - 1 : year;
      return budgetApi.applyRollover(prevYear, prevMonth);
    },
    onSuccess: invalidate,
  });

  // month: 0 is the "every month" allocation. Budgets are set that way by
  // default so a new month doesn't silently start unbudgeted.
  function saveEdit(catId: number, amount: string) {
    upsertMut.mutate({ category_id: catId, year, month: 0, budgeted_amount: parseFloat(amount) });
  }
  function toggle(id: number) {
    setExpanded(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  const allocByCat: Record<number, any> = {};
  allocations.forEach(a => { allocByCat[a.category_id] = a; });

  // A budget line is an EXPENSE category with an allocation, at whatever level
  // it was set. Dan budgets at the level he thinks in (Subscriptions), which
  // is a child of Wants, so filtering to parentless rows would hide every real
  // budget he has. Income categories are dropped outright -- "Income" and
  // "Salary / Wages" carry $12,133.26 allocations that are forecasting inputs,
  // not spending limits, and counting them wrecked the headline totals.
  const withBudget = overview.filter(
    r => parseFloat(r.budgeted || "0") > 0 && (r.category_type ?? "expense") === "expense",
  );

  // When a parent AND its children are both budgeted, the parent governs and
  // the children fold into it. Dan's real data budgets Necessities at
  // $6,200.53 and also Mortgage/Rent, Groceries and Vehicles beneath it;
  // summing all four counted the same dollars twice. This is also the
  // behaviour he asked for -- a handful of broad lines to hit rather than a
  // limit per sub-category, with the detail still one expand away.
  const governedByParent = new Set(
    withBudget
      .filter(r => r.parent_id && withBudget.some(p => p.category_id === r.parent_id))
      .map(r => r.category_id),
  );
  const budgetRows = withBudget
    .filter(r => !governedByParent.has(r.category_id))
    .sort((a, b) => parseFloat(b.budgeted) - parseFloat(a.budgeted));

  // Spend with no budget behind it. This is the "what should I budget for?"
  // question, answered in place instead of on the Spending page.
  // Exclude both directions of an already-budgeted relationship. A child of a
  // budgeted parent is already covered by that line, and a PARENT of budgeted
  // children is too -- its actual_total is their rolled-up spend, so offering
  // to budget it would double-count. Without the second check the demo data
  // offered Necessities ($4,258.89), Wants and Charity as unbudgeted while
  // every category beneath them already had a line.
  const budgetedParentIds = new Set(budgetRows.map(r => r.parent_id).filter(Boolean));
  const unbudgeted = overview
    .filter(r => (r.category_type ?? "expense") === "expense")
    .filter(r => parseFloat(r.budgeted || "0") === 0 && parseFloat(r.actual_total || "0") > 0)
    .filter(r => !budgetRows.some(b => b.category_id === r.parent_id))
    .filter(r => !budgetedParentIds.has(r.category_id))
    .sort((a, b) => parseFloat(b.actual_total) - parseFloat(a.actual_total));

  function availableOf(row: RowShape): number {
    return parseFloat(row.budgeted || "0") +
      (row.rollover_enabled ? parseFloat(row.rollover_balance || "0") : 0);
  }

  const totalAvailable = budgetRows.reduce((s, r) => s + availableOf(r), 0);
  const totalSpent = budgetRows.reduce((s, r) => s + parseFloat(r.actual_total || "0"), 0);
  const totalLeft = totalAvailable - totalSpent;
  const overallPct = totalAvailable > 0 ? (totalSpent / totalAvailable) * 100 : 0;
  const overCount = budgetRows.filter(r => parseFloat(r.actual_total || "0") > availableOf(r)).length;

  const budgetedIds = new Set(budgetRows.map(r => r.category_id));
  const addable = categories
    .filter((c: any) => c.type === "expense" && !budgetedIds.has(c.id))
    .sort((a: any, b: any) => a.name.localeCompare(b.name));

  function Breakdown({ categoryId }: { categoryId: number }) {
    const { data: merchants = [], isLoading: loadingM } = useQuery<any[]>({
      queryKey: ["budget-breakdown", categoryId, year, month],
      queryFn: () => budgetApi.categoryBreakdown(categoryId, year, month),
    });
    if (loadingM) return <p className="text-xs text-gray-400 py-2 pl-6">Loading…</p>;
    if (merchants.length === 0) return <p className="text-xs text-gray-400 py-2 pl-6">Nothing spent here yet.</p>;
    return (
      <div className="pl-6 pb-2 space-y-1">
        {merchants.map((m: any) => (
          <div key={m.name} className="flex items-baseline justify-between gap-3 text-xs">
            <span className="truncate text-gray-600 dark:text-gray-400">{m.name}</span>
            <span className="shrink-0 tabular-nums text-gray-700 dark:text-gray-300">
              {fmt(m.total)}
              <span className="ml-1.5 text-gray-400">{m.count}x</span>
            </span>
          </div>
        ))}
      </div>
    );
  }

  function BudgetRow({ row }: { row: RowShape }) {
    const available = availableOf(row);
    const spent = parseFloat(row.actual_total || "0");
    const left = available - spent;
    const pct = available > 0 ? (spent / available) * 100 : 0;
    const isOpen = expanded.has(row.category_id);
    const alloc = allocByCat[row.category_id];

    return (
      <div className="py-3 border-b border-gray-50 dark:border-gray-800 last:border-0">
        <div className="flex items-baseline justify-between gap-3 mb-1.5">
          <div className="flex items-center gap-1.5 min-w-0">
            <button onClick={() => toggle(row.category_id)} className="text-gray-400 hover:text-indigo-500 shrink-0">
              {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
            <span className="truncate font-medium text-gray-900 dark:text-white">{row.category_name}</span>
            {row.rollover_enabled && parseFloat(row.rollover_balance || "0") > 0 && (
              <span className="shrink-0 text-xs px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                +{fmt(parseFloat(row.rollover_balance || "0"))} rolled over
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {editId === row.category_id ? (
              <div className="flex items-center gap-1">
                <input type="number" step="0.01" className="input w-24 py-0.5 text-right text-sm"
                  value={editAmt} onChange={e => setEditAmt(e.target.value)} autoFocus />
                <button onClick={() => saveEdit(row.category_id, editAmt)} className="text-emerald-600"><Check size={14} /></button>
                <button onClick={() => setEditId(null)} className="text-gray-400"><X size={14} /></button>
              </div>
            ) : (
              <>
                <span className="text-sm tabular-nums text-gray-500 dark:text-gray-400">
                  {fmt(spent)}<span className="text-gray-300 dark:text-gray-400"> / {fmt(available)}</span>
                </span>
                <button onClick={() => { setEditId(row.category_id); setEditAmt(row.budgeted); }}
                  className="text-gray-300 hover:text-indigo-500" title="Change budget">
                  <Pencil size={12} />
                </button>
                {alloc && (
                  <button onClick={() => deleteMut.mutate(alloc.id)}
                    className="text-gray-300 hover:text-red-500" title="Remove this budget line">
                    <Trash2 size={12} />
                  </button>
                )}
              </>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex-1 h-1.5 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
            <div className={`h-full rounded-full ${barColor(pct)}`} style={{ width: `${Math.min(pct, 100)}%` }} />
          </div>
          <span className={`text-xs tabular-nums shrink-0 ${left < 0 ? "text-red-600 dark:text-red-400" : "text-gray-400"}`}>
            {left < 0 ? `${fmt(Math.abs(left))} over` : `${fmt(left)} left`}
          </span>
        </div>

        {isOpen && (
          <div className="mt-2">
            <Breakdown categoryId={row.category_id} />
            <label className="flex items-center gap-2 pl-6 pt-1 text-xs text-gray-500 dark:text-gray-400 cursor-pointer">
              <input type="checkbox" checked={!!row.rollover_enabled}
                onChange={e => rolloverToggleMut.mutate({ id: row.category_id, enabled: e.target.checked })} />
              Roll unspent budget into next month
            </label>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Budget</h2>
          <button onClick={() => setShowHelp(true)} className="text-gray-300 hover:text-indigo-500">
            <HelpCircle size={14} />
          </button>
        </div>
        <div className="flex items-center gap-2">
          <select className="input py-1 text-sm" value={month} onChange={e => setMonth(Number(e.target.value))}>
            {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
          </select>
          <select className="input py-1 text-sm w-24" value={year} onChange={e => setYear(Number(e.target.value))}>
            {[year - 1, year, year + 1].map(y => <option key={y} value={y}>{y}</option>)}
          </select>
          <button onClick={() => applyRolloverMut.mutate()} disabled={applyRolloverMut.isPending}
            className="btn-secondary text-xs px-2 py-1" title="Carry last month's unspent budget forward">
            <RotateCcw size={12} /> Rollover
          </button>
        </div>
      </div>

      {isLoading && <div className="card text-sm text-gray-400">Loading…</div>}

      {!isLoading && (
        <>
          <div className="card bg-gradient-to-br from-indigo-50 to-white dark:from-indigo-950/30 dark:to-transparent">
            <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
              {MONTHS[month - 1]} {year}
            </p>
            <p className={`text-3xl font-bold mt-1 ${totalLeft < 0 ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"}`}>
              {totalLeft < 0 ? `${fmt(Math.abs(totalLeft))} over` : `${fmt(totalLeft)} left to spend`}
            </p>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              {fmt(totalSpent)} spent of {fmt(totalAvailable)} budgeted
              {overCount > 0 && <span className="text-red-500"> · {overCount} over budget</span>}
            </p>
            <div className="mt-3 h-2 rounded-full bg-white/70 dark:bg-gray-800 overflow-hidden">
              <div className={`h-full rounded-full ${barColor(overallPct)}`} style={{ width: `${Math.min(overallPct, 100)}%` }} />
            </div>
          </div>

          <div className="card">
            <div className="flex items-center justify-between mb-1">
              <h3 className="font-semibold text-gray-900 dark:text-white">Budget lines</h3>
              <button onClick={() => setAdding(v => !v)} className="btn-secondary text-xs px-2 py-1">
                <Plus size={12} /> Add
              </button>
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
              A few broad lines are easier to hit than many small ones. Expand any line to see what made it up.
            </p>

            {adding && (
              <div className="flex flex-wrap items-center gap-2 mb-3 bg-gray-50 dark:bg-gray-800/50 rounded-md px-3 py-2">
                <select className="input py-1 text-sm" value={addCat} onChange={e => setAddCat(e.target.value)}>
                  <option value="">Choose a category…</option>
                  {addable.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
                <input type="number" step="0.01" className="input w-28 py-1 text-sm text-right"
                  placeholder="Amount" value={addAmt} onChange={e => setAddAmt(e.target.value)} />
                <button className="btn-primary text-xs px-2 py-1" disabled={!addCat || !addAmt || upsertMut.isPending}
                  onClick={() => saveEdit(Number(addCat), addAmt)}>
                  {upsertMut.isPending ? "Saving…" : "Add"}
                </button>
                <button className="text-xs text-gray-400 hover:text-gray-600" onClick={() => setAdding(false)}>Cancel</button>
              </div>
            )}

            {budgetRows.length === 0 && (
              <p className="text-sm text-gray-400 py-4 text-center">
                No budget lines yet. Add one, or start from what you already spend below.
              </p>
            )}
            {budgetRows.map(r => <BudgetRow key={r.category_id} row={r} />)}
          </div>

          {unbudgeted.length > 0 && (
            <div className="card">
              <h3 className="font-semibold text-gray-900 dark:text-white">Spending with no budget</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
                What you spent here this month. Budget it at that amount in one click, then adjust.
              </p>
              <div className="space-y-2">
                {unbudgeted.map(r => (
                  <div key={r.category_id} className="flex items-center justify-between gap-3">
                    <span className="text-sm text-gray-700 dark:text-gray-300 truncate">{r.category_name}</span>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-sm tabular-nums text-gray-500 dark:text-gray-400">
                        {fmt(parseFloat(r.actual_total))}
                      </span>
                      <button className="btn-secondary text-xs px-2 py-0.5"
                        disabled={upsertMut.isPending}
                        onClick={() => saveEdit(r.category_id, r.actual_total)}>
                        Budget this
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {showHelp && (
        <HelpPanel
          title="Budget"
          body={
            "Set a few broad budget lines rather than many small ones — a single Subscriptions budget is easier to hit than a limit per service.\n\n" +
            "Expand any line to see the merchants that made it up this month.\n\n" +
            "Budgets are saved as 'every month' by default, so a new month never starts unbudgeted. Removing a line is different from setting it to zero: zero means spend nothing here, while removing it means the category simply isn't budgeted.\n\n" +
            "'Spending with no budget' shows where money went that no line covers, so you can budget it at what you actually spend."
          }
          onClose={() => setShowHelp(false)}
        />
      )}
    </div>
  );
}

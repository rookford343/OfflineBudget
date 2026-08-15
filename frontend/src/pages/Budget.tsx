import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { budgetApi } from "../api";
import { fmt } from "../lib/utils";
import { Pencil, Check, X, RotateCcw, HelpCircle, ChevronRight, ChevronDown } from "lucide-react";
import HelpPanel from "../components/HelpPanel";

/**
 * Rewritten 2026-08-15. The old page was an 8-column table -- Budget,
 * Rollover, Available, Checking, Cards, Total, Left -- where four columns
 * were arithmetic on the other four (Available = Budget + Rollover,
 * Total = Checking + Cards, Left = Available - Total). It showed every
 * category whether budgeted or not, had no summary anywhere, and put the
 * one number that matters (are I over or under?) in the last column of a
 * horizontally-scrolling table.
 *
 * Now: one headline answering "how much is left this month", then a row per
 * category with a progress bar. Checking/Cards collapse into one figure and
 * expand on demand -- the split is real but it's a detail, not the point.
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
}

export default function Budget() {
  const now = new Date();
  const [showHelp, setShowHelp] = useState(false);
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [editId, setEditId] = useState<number | null>(null);
  const [editAmt, setEditAmt] = useState("");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [showUnbudgeted, setShowUnbudgeted] = useState(false);
  const qc = useQueryClient();

  const { data: overview = [], isLoading } = useQuery<RowShape[]>({
    queryKey: ["budget-overview", year, month],
    queryFn: () => budgetApi.overview(year, month),
  });

  const upsertMut = useMutation({
    mutationFn: budgetApi.upsert,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["budget-overview"] }); setEditId(null); },
  });
  const rolloverToggleMut = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => budgetApi.setCategoryRollover(id, enabled),
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
  function toggle(id: number) {
    setExpanded(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  const tops = overview.filter(r => !r.parent_id);
  const subsByParent: Record<number, RowShape[]> = {};
  overview.filter(r => r.parent_id).forEach(s => { (subsByParent[s.parent_id!] ??= []).push(s); });

  // A parent's own budget row is usually empty because budgeting happens at
  // the leaf, so roll children up rather than showing the parent as $0.
  function budgetOf(row: RowShape): number {
    const own = parseFloat(row.budgeted || "0");
    const kids = (subsByParent[row.category_id] ?? [])
      .reduce((s, k) => s + parseFloat(k.budgeted || "0"), 0);
    return own + kids;
  }
  function availableOf(row: RowShape): number {
    return budgetOf(row) + (row.rollover_enabled ? parseFloat(row.rollover_balance || "0") : 0);
  }

  const budgetedRows = tops.filter(r => availableOf(r) > 0 || parseFloat(r.actual_total || "0") > 0);
  const unbudgetedRows = tops.filter(r => !budgetedRows.includes(r));

  const totalAvailable = budgetedRows.reduce((s, r) => s + availableOf(r), 0);
  const totalSpent = budgetedRows.reduce((s, r) => s + parseFloat(r.actual_total || "0"), 0);
  const totalLeft = totalAvailable - totalSpent;
  const overallPct = totalAvailable > 0 ? (totalSpent / totalAvailable) * 100 : 0;
  const overCount = budgetedRows.filter(r => {
    const a = availableOf(r);
    return a > 0 && parseFloat(r.actual_total || "0") > a;
  }).length;

  function CategoryRow({ row, isSub = false }: { row: RowShape; isSub?: boolean }) {
    const available = isSub
      ? parseFloat(row.budgeted || "0") + (row.rollover_enabled ? parseFloat(row.rollover_balance || "0") : 0)
      : availableOf(row);
    const spent = parseFloat(row.actual_total || "0");
    const left = available - spent;
    const pct = available > 0 ? (spent / available) * 100 : 0;
    const kids = subsByParent[row.category_id] ?? [];
    const isOpen = expanded.has(row.category_id);
    const checking = parseFloat(row.actual_checking || "0");
    const cards = parseFloat(row.actual_cards || "0");

    return (
      <div className={isSub ? "pl-6 border-l-2 border-gray-100 dark:border-gray-800 ml-3" : ""}>
        <div className="py-3 border-b border-gray-50 dark:border-gray-800 last:border-0">
          <div className="flex items-baseline justify-between gap-3 mb-1.5">
            <div className="flex items-center gap-1.5 min-w-0">
              {(kids.length > 0 || checking > 0) && !isSub ? (
                <button onClick={() => toggle(row.category_id)} className="text-gray-400 hover:text-indigo-500 shrink-0">
                  {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </button>
              ) : <span className="w-[14px] shrink-0" />}
              <span className={`truncate ${isSub ? "text-sm text-gray-600 dark:text-gray-400" : "font-medium text-gray-900 dark:text-white"}`}>
                {row.category_name}
              </span>
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
                  <button onClick={() => saveEdit(row.category_id)} className="text-emerald-600"><Check size={14} /></button>
                  <button onClick={() => setEditId(null)} className="text-gray-400"><X size={14} /></button>
                </div>
              ) : (
                <>
                  <span className="text-sm tabular-nums text-gray-500 dark:text-gray-400">
                    {fmt(spent)}{available > 0 && <span className="text-gray-300 dark:text-gray-600"> / {fmt(available)}</span>}
                  </span>
                  <button onClick={() => { setEditId(row.category_id); setEditAmt(row.budgeted); }}
                    className="text-gray-300 hover:text-indigo-500" title="Set budget">
                    <Pencil size={12} />
                  </button>
                </>
              )}
            </div>
          </div>

          {available > 0 ? (
            <div className="flex items-center gap-3">
              <div className="flex-1 h-2 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                <div className={`h-full rounded-full transition-all ${barColor(pct)}`} style={{ width: `${Math.min(100, pct)}%` }} />
              </div>
              <span className={`text-xs tabular-nums shrink-0 w-28 text-right font-medium ${left < 0 ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"}`}>
                {left < 0 ? `${fmt(Math.abs(left))} over` : `${fmt(left)} left`}
              </span>
            </div>
          ) : (
            <p className="text-xs text-gray-400">No budget set{spent > 0 ? ` · ${fmt(spent)} spent` : ""}</p>
          )}

          {isOpen && !isSub && (
            <div className="mt-2 space-y-1">
              {(checking > 0 || cards > 0) && (
                <p className="text-xs text-gray-400 pl-5">
                  {fmt(checking)} from checking · {fmt(cards)} on cards
                </p>
              )}
              <label className="flex items-center gap-1.5 pl-5 cursor-pointer w-fit" title="Carry unspent budget into next month">
                <input type="checkbox" checked={!!row.rollover_enabled}
                  onChange={e => rolloverToggleMut.mutate({ id: row.category_id, enabled: e.target.checked })}
                  className="w-3 h-3 accent-indigo-500" />
                <span className="text-xs text-gray-400">Roll unspent budget into next month</span>
              </label>
            </div>
          )}
        </div>
        {isOpen && kids.map(k => <CategoryRow key={k.category_id} row={k} isSub />)}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-1.5">
            Budget
            <button onClick={() => setShowHelp(true)} className="text-gray-400 hover:text-indigo-500 font-normal"><HelpCircle size={15} /></button>
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400">What you planned to spend, and what you actually have left</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <select className="input w-auto" value={month} onChange={e => setMonth(parseInt(e.target.value))}>
            {MONTHS.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
          </select>
          <select className="input w-auto" value={year} onChange={e => setYear(parseInt(e.target.value))}>
            {[-1, 0, 1].map(d => <option key={d} value={now.getFullYear() + d}>{now.getFullYear() + d}</option>)}
          </select>
        </div>
      </div>

      {/* The answer, before any detail. */}
      {!isLoading && (
        <div className={`card ${totalLeft < 0
          ? "bg-gradient-to-br from-red-50 to-orange-50 border-red-100 dark:from-red-950/40 dark:to-orange-950/30 dark:border-red-900/50"
          : "bg-gradient-to-br from-emerald-50 to-teal-50 border-emerald-100 dark:from-emerald-950/40 dark:to-teal-950/30 dark:border-emerald-900/50"}`}>
          <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">
            {MONTHS[month - 1]} {year}
          </p>
          <p className={`text-3xl font-bold tabular-nums ${totalLeft < 0 ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"}`}>
            {totalLeft < 0 ? `${fmt(Math.abs(totalLeft))} over budget` : `${fmt(totalLeft)} left to spend`}
          </p>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
            {fmt(totalSpent)} spent of {fmt(totalAvailable)} budgeted
            {overCount > 0 && (
              <span className="text-red-600 dark:text-red-400"> · {overCount} categor{overCount === 1 ? "y" : "ies"} over</span>
            )}
          </p>
          <div className="mt-3 h-2.5 bg-white/70 dark:bg-black/30 rounded-full overflow-hidden">
            <div className={`h-full rounded-full transition-all ${barColor(overallPct)}`} style={{ width: `${Math.min(100, overallPct)}%` }} />
          </div>
        </div>
      )}

      <div className="card">
        {isLoading && <p className="text-sm text-gray-400 text-center py-8">Loading…</p>}
        {!isLoading && budgetedRows.length === 0 && (
          <p className="text-sm text-gray-400 text-center py-8">
            No budgets set yet. Click the pencil next to a category below to set one.
          </p>
        )}
        {!isLoading && budgetedRows.map(row => <CategoryRow key={row.category_id} row={row} />)}
      </div>

      {!isLoading && unbudgetedRows.length > 0 && (
        <div className="card">
          <button onClick={() => setShowUnbudgeted(v => !v)}
            className="flex items-center gap-1.5 text-sm text-gray-500 dark:text-gray-400 hover:text-indigo-500">
            {showUnbudgeted ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            {unbudgetedRows.length} categor{unbudgetedRows.length === 1 ? "y" : "ies"} with no budget and no spending
          </button>
          {showUnbudgeted && (
            <div className="mt-2">
              {unbudgetedRows.map(row => <CategoryRow key={row.category_id} row={row} />)}
            </div>
          )}
        </div>
      )}

      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className="text-xs text-gray-400 dark:text-gray-500">
          Budgets apply to every month. Expand a category to split checking vs cards, or turn on rollover.
        </p>
        <button onClick={() => applyRolloverMut.mutate()} disabled={applyRolloverMut.isPending}
          className="btn-secondary flex items-center gap-1.5 text-xs"
          title="Carry last month's unspent budget forward into rollover-enabled categories">
          <RotateCcw size={13} className={applyRolloverMut.isPending ? "animate-spin" : ""} />
          Apply last month's rollover
        </button>
      </div>

      {showHelp && <HelpPanel title="Budget" body={"Set a monthly target per category, then track what's actually been spent against it.\n\nThe number at the top is the whole page in one line: everything budgeted, minus everything spent.\n\nEach bar turns amber at 80% and red once you pass 100%.\n\nSpending comes from your imported transactions and card charges. Expand a category to see the checking/card split.\n\nRollover carries unspent budget into next month — useful for irregular costs like car repair."} onClose={() => setShowHelp(false)} />}
    </div>
  );
}

import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { budgetApi, categoriesApi } from "../api";
import { fmt, cx } from "../lib/utils";
import { Pencil, Check, X, RotateCcw, HelpCircle, ChevronRight, ChevronDown, Plus, Trash2 } from "lucide-react";
import HelpPanel from "../components/HelpPanel";
import HowCalculated from "../components/HowCalculated";
import MonthYearPicker from "../components/MonthYearPicker";
import { CategoryOptions } from "../lib/selectOptions";
import {
  availableOf, flexibleSaveMonth, leftToAssignStatus, trackTotals, unbudgetedSpend,
  type OverviewRow, type PlanTrackLine,
} from "../lib/budgetPlan";

/**
 * Reworked 2026-08-16 around how the user actually budgets: a handful of
 * top-level lines (Subscriptions, Shopping) that are easier to hit than a
 * dozen sub-limits, each expanding to show the merchants that add up to it.
 *
 * Reworked again 2026-10-19: Set Budgets is ONE list. Each category shows
 * Committed (from Recurring, automatic), Flexible (what you add) and Budget
 * (the two together), and the header reads Income − Committed − Flexible =
 * Left to assign. It replaces a separate Left to budget panel whose numbers
 * never reconciled with the list beneath it. All of the math comes from
 * GET /budget/plan; Track Budgets measures the same per-line Budget.
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function barColor(pct: number): string {
  if (pct >= 100) return "bg-red-500";
  if (pct >= 80) return "bg-amber-500";
  return "bg-emerald-500";
}

interface PlanItem { name: string; amount: string; times: number; recurring_item_id?: number | null; planned_expense_id?: number | null }
interface PlanRow {
  category_id: number | null; category_name: string;
  committed: string; flexible: string; budget: string;
  is_set: boolean; is_assignable: boolean; editable: boolean; items: PlanItem[];
}
interface PlanGroup {
  group_id: number | null; group_name: string; kind: "parent" | "other" | "uncategorized";
  rows: PlanRow[]; committed: string; flexible: string; budget: string;
  parent_line: string | null; rest: string; parent_line_short: string;
}
interface Plan {
  income_total: string; committed_total: string; flexible_total: string; budget_total: string;
  left_to_assign: string; category_budget_total: string; unclassified_count: number;
  carry_forward: boolean; groups: PlanGroup[]; lines: PlanTrackLine[]; explain_left_to_assign: any;
}

type BudgetTab = "track" | "set";

// The Set list's line layout. Below `sm` a line is the name with a small
// labelled Committed / Flexible / Budget grid under it. From `sm` up the
// amounts are columns, narrow enough (3 x 5.5rem + gaps) that the name keeps
// at least 8rem even at `md` with the sidebar open.
const COLS = "sm:grid-cols-[minmax(8rem,1fr)_5.5rem_minmax(5.5rem,7rem)_5.5rem] sm:items-center sm:gap-2";
const ROW = `flex flex-col gap-1 sm:grid ${COLS}`;

export default function Budget() {
  const now = new Date();
  const [showHelp, setShowHelp] = useState(false);
  // Split into Track (monitoring) and Set (config) tabs (the user,
  // 2026-09-08): "configuration screens show the number you set; monitoring
  // screens show the number relative to reality". Track is the default.
  const [tab, setTab] = useState<BudgetTab>("track");
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [editKey, setEditKey] = useState<string | null>(null);
  const [editAmt, setEditAmt] = useState("");
  // Which editor/button the in-flight (or last failed) save belongs to, so
  // pending and failure state show on that row only.
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [adding, setAdding] = useState(false);
  const [addCat, setAddCat] = useState("");
  const [addAmt, setAddAmt] = useState("");
  const qc = useQueryClient();

  // Keyed "left-to-budget" on purpose: the Recurring triage inbox, the
  // Categories tab and the carry-forward setting already invalidate that
  // prefix whenever they change something this view depends on.
  const { data: plan, isLoading, isError: planFailed, refetch: refetchPlan, isFetching: planFetching } = useQuery<Plan>({
    queryKey: ["left-to-budget", year, month],
    queryFn: () => budgetApi.plan(year, month),
  });
  const { data: overview = [] } = useQuery<OverviewRow[]>({
    queryKey: ["budget-overview", year, month],
    queryFn: () => budgetApi.overview(year, month),
  });
  // Allocations carry the id that DELETE needs.
  const { data: allocations = [] } = useQuery<any[]>({
    queryKey: ["budget-allocations", year],
    queryFn: () => budgetApi.list(year),
  });
  const { data: categories = [] } = useQuery<any[]>({
    queryKey: ["categories"],
    queryFn: categoriesApi.list,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["left-to-budget"] });
    qc.invalidateQueries({ queryKey: ["budget-overview"] });
    qc.invalidateQueries({ queryKey: ["budget-allocations"] });
  };

  const upsertMut = useMutation({
    mutationFn: budgetApi.upsert,
    onSuccess: () => { invalidate(); setEditKey(null); setAdding(false); setAddCat(""); setAddAmt(""); },
  });
  const deleteMut = useMutation({ mutationFn: budgetApi.remove, onSuccess: invalidate });
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

  const carryForward = !!plan?.carry_forward;
  const assignableIds = new Set(overview.filter(r => r.is_assignable).map(r => r.category_id));
  const monthOnly = (catId: number) => flexibleSaveMonth(month, assignableIds.has(catId), carryForward) !== 0;
  const monthLabel = `${MONTHS[month - 1]} ${year}`;
  function save(catId: number, amount: string, key: string) {
    setSavingKey(key);
    upsertMut.mutate({
      category_id: catId, year,
      month: flexibleSaveMonth(month, assignableIds.has(catId), carryForward),
      budgeted_amount: parseFloat(amount || "0"),
    });
  }
  function toggle(key: string) {
    setExpanded(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }

  // The allocation that governs the viewed month: its month row if there is
  // one, else the every-month row. The trash button only removes that.
  const allocByCat: Record<number, any> = {};
  allocations.forEach(a => {
    if (a.month === month || (a.month === 0 && allocByCat[a.category_id]?.month !== month)) {
      allocByCat[a.category_id] = a;
    }
  });

  const lines = plan?.lines ?? [];
  const totals = trackTotals(lines);
  const unbudgeted = unbudgetedSpend(overview, lines);
  const shownIds = new Set(
    (plan?.groups ?? []).flatMap(g => [
      ...g.rows.filter(r => r.editable && r.category_id != null).map(r => r.category_id as number),
      ...(g.parent_line != null && g.group_id != null ? [g.group_id] : []),
    ]),
  );

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

  /** An inline amount editor. `k` identifies what's being edited. While its
   * save is in flight the input and buttons are disabled; if the save fails
   * the editor stays open with the typed value and says so. */
  // Plain render functions, not components: a component declared inside
  // Budget is a new type on every render, which would remount the input and
  // drop focus on each keystroke.
  function amountEditor({ k, value, onSave, title }: { k: string; value: string; onSave: (v: string) => void; title: string }) {
    if (editKey === k) {
      const saving = upsertMut.isPending && savingKey === k;
      const failed = upsertMut.isError && savingKey === k;
      return (
        <div className="flex flex-col items-start sm:items-end gap-0.5 min-w-0 w-full">
          <div className="flex flex-wrap items-center justify-start sm:justify-end gap-1 min-w-0 w-full">
            <input type="number" step="0.01" min="0" aria-label={title} disabled={saving}
              className="input min-w-0 w-full max-w-[7rem] py-0.5 text-right text-sm"
              value={editAmt} onChange={e => setEditAmt(e.target.value)} autoFocus
              onKeyDown={e => { if (e.key === "Enter" && !saving) onSave(editAmt); if (e.key === "Escape" && !saving) setEditKey(null); }} />
            <span className="flex items-center gap-1">
              <button onClick={() => onSave(editAmt)} disabled={saving} className="text-emerald-600 disabled:opacity-40" aria-label="Save"><Check size={14} /></button>
              <button onClick={() => setEditKey(null)} disabled={saving} className="text-gray-400 disabled:opacity-40" aria-label="Cancel"><X size={14} /></button>
            </span>
          </div>
          {saving && <span className="text-xs text-gray-400">Saving…</span>}
          {failed && <span role="alert" className="text-xs text-red-500">Save failed — try again</span>}
        </div>
      );
    }
    return (
      <div className="flex items-center justify-start sm:justify-end gap-1.5">
        <span className="text-sm tabular-nums text-gray-700 dark:text-gray-300">{fmt(value)}</span>
        <button onClick={() => { upsertMut.reset(); setEditKey(k); setEditAmt(String(parseFloat(value || "0"))); }}
          className="text-gray-300 hover:text-indigo-500" title={title} aria-label={title}>
          <Pencil size={12} />
        </button>
      </div>
    );
  }

  /** One responsive line: below `sm` the three amounts stack under the name
   * as a small labelled grid; from `sm` up they are columns of the list. */
  function line4(name: React.ReactNode, committed: React.ReactNode, flexible: React.ReactNode, budget: React.ReactNode, className = "") {
    const cell = (label: string, content: React.ReactNode) => (
      <div className="flex min-w-0 flex-col items-start sm:items-end">
        <span className="sm:hidden text-[10px] uppercase tracking-wide text-gray-400">{label}</span>
        {content}
      </div>
    );
    return (
      <div className={cx(ROW, className)}>
        <div className="min-w-0">{name}</div>
        <div className="grid grid-cols-3 gap-2 sm:contents">
          {cell("Committed", committed)}
          {cell("Flexible", flexible)}
          {cell("Budget", budget)}
        </div>
      </div>
    );
  }

  function committedCell(row: PlanRow, k: string) {
    const has = row.items.length > 0;
    return (
      <button type="button" disabled={!has} onClick={() => toggle(k)}
        className={cx("flex items-center gap-1 text-sm tabular-nums",
          has ? "text-gray-700 dark:text-gray-300 hover:text-indigo-500" : "text-gray-400")}
        aria-label={has ? `${expanded.has(k) ? "Hide" : "Show"} the recurring items behind ${row.category_name}` : undefined}>
        {has && (expanded.has(k) ? <ChevronDown size={12} /> : <ChevronRight size={12} />)}
        {fmt(row.committed)}
      </button>
    );
  }

  function planRow(row: PlanRow, group: PlanGroup) {
    const k = `${group.group_name}:${row.category_id ?? row.category_name}`;
    const cid = row.category_id;
    const alloc = cid != null ? allocByCat[cid] : undefined;
    const ov = cid != null ? overview.find(r => r.category_id === cid) as any : undefined;
    return (
      <div className="py-2 border-b border-gray-50 dark:border-gray-800 last:border-0">
        {line4(
          <div className="flex items-center gap-2 min-w-0 pl-3">
            <span className="truncate text-sm text-gray-900 dark:text-white">
              {group.kind === "uncategorized"
                ? <Link to="/recurring" className="text-amber-600 underline">{row.category_name}</Link>
                : row.category_name}
            </span>
            {row.editable && cid != null && monthOnly(cid) && (
              <span className="shrink-0 text-xs text-gray-400" title="Carry-forward is off, so this bucket is set month by month">
                {monthLabel} only
              </span>
            )}
          </div>,
          committedCell(row, k),
          row.editable && cid != null
            ? amountEditor({ k: `flex:${cid}`, value: row.flexible, title: `Change flexible amount for ${row.category_name}`,
                onSave: v => save(cid, v, `flex:${cid}`) })
            : <span className="text-sm tabular-nums text-gray-400">—</span>,
          <div className="flex items-center gap-1.5">
            <span className="text-sm font-medium tabular-nums text-gray-900 dark:text-white">{fmt(row.budget)}</span>
            {alloc && row.editable && (
              <button onClick={() => deleteMut.mutate(alloc.id)}
                className="text-gray-300 hover:text-red-500" title="Remove the flexible amount (bills stay)"
                aria-label={`Remove flexible amount for ${row.category_name}`}>
                <Trash2 size={12} />
              </button>
            )}
          </div>,
        )}
        {row.editable && cid != null && (
          <div className="flex items-center gap-3 pl-3 mt-0.5">
            <label className="flex items-center gap-1 text-xs text-gray-400 cursor-pointer">
              <input type="checkbox" checked={!!ov?.rollover_enabled}
                onChange={e => rolloverToggleMut.mutate({ id: cid, enabled: e.target.checked })} />
              Rollover
            </label>
            {ov?.rollover_enabled && parseFloat(ov?.rollover_balance || "0") > 0 && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                +{fmt(parseFloat(ov.rollover_balance))} rolled over
              </span>
            )}
          </div>
        )}
        {expanded.has(k) && row.items.length > 0 && (
          <div className="mt-1 ml-6 space-y-0.5">
            {row.items.map(i => (
              <div key={`${i.recurring_item_id ?? "p" + i.planned_expense_id}`}
                className="flex justify-between gap-3 text-xs text-gray-500 dark:text-gray-400">
                <span className="truncate">
                  {i.name}
                  {i.times > 1 && <span className="ml-1 text-gray-400">×{i.times}</span>}
                  {i.planned_expense_id != null && <span className="ml-1 text-gray-400">one-off</span>}
                </span>
                <span className="tabular-nums shrink-0">{fmt(i.amount)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  function groupView(group: PlanGroup) {
    const gid = group.group_id;
    const parentAlloc = gid != null ? allocByCat[gid] : undefined;
    const hasLine = group.parent_line != null;
    const amt = (v: string, strong = false) => (
      <span className={cx("text-xs tabular-nums", strong ? "font-semibold text-gray-700 dark:text-gray-300" : "text-gray-500")}>{fmt(v)}</span>
    );
    return (
      <div className="mt-3 first:mt-0">
        {line4(
          <span className="block truncate text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">{group.group_name}</span>,
          amt(group.committed), amt(group.flexible), amt(group.budget, true),
          "py-1.5 border-b border-gray-200 dark:border-gray-700",
        )}
        {hasLine && gid != null && (
          <div className="py-2 border-b border-gray-50 dark:border-gray-800">
            {line4(
              <span className="block pl-3 text-sm text-gray-900 dark:text-white truncate">{group.group_name} total</span>,
              <span className="text-sm text-gray-400">—</span>,
              amountEditor({ k: `line:${gid}`, value: group.parent_line as string,
                title: `Change the ${group.group_name} group total`, onSave: v => save(gid, v, `line:${gid}`) }),
              parentAlloc ? (
                <button onClick={() => deleteMut.mutate(parentAlloc.id)}
                  className="text-gray-300 hover:text-red-500" title="Remove the group total; the rows below then add up on their own"
                  aria-label={`Remove the ${group.group_name} group total`}>
                  <Trash2 size={12} />
                </button>
              ) : <span />,
            )}
            <p className="pl-3 mt-0.5 text-xs text-gray-400">
              A line set on {group.group_name} itself counts as the group's total: the bills and flexible amounts below sit inside it, not on top of it.
              {parseFloat(group.rest) > 0 && <> {fmt(group.rest)} of it isn't assigned to a row yet.</>}
            </p>
            {parseFloat(group.parent_line_short) > 0 && (
              <p className="pl-3 mt-0.5 text-xs text-amber-600 dark:text-amber-400">
                The rows below need {fmt(group.parent_line_short)} more than this total, so the group's Budget uses the rows.
              </p>
            )}
          </div>
        )}
        {group.rows.map(r => <React.Fragment key={`${r.category_id ?? r.category_name}`}>{planRow(r, group)}</React.Fragment>)}
        {hasLine && parseFloat(group.rest) > 0 && line4(
          <span className="block pl-3 text-sm italic text-gray-500 dark:text-gray-400 truncate">Rest of {group.group_name}</span>,
          <span className="text-sm text-gray-400">—</span>,
          <span className="text-sm tabular-nums text-gray-500">{fmt(group.rest)}</span>,
          <span className="text-sm tabular-nums text-gray-500">{fmt(group.rest)}</span>,
          "py-2 border-b border-gray-50 dark:border-gray-800",
        )}
      </div>

    );
  }

  // Track Budgets: the Budget relative to reality. Read-only.
  function monitorRow(line: PlanTrackLine) {
    const available = availableOf(line);
    const spent = parseFloat(line.actual_total || "0");
    const left = available - spent;
    const pct = available > 0 ? (spent / available) * 100 : 0;
    const k = `track:${line.category_id}`;
    const isOpen = expanded.has(k);
    return (
      <div className="py-3 border-b border-gray-50 dark:border-gray-800 last:border-0">
        <div className="flex items-baseline justify-between gap-3 mb-1.5">
          <div className="flex items-center gap-1.5 min-w-0">
            <button onClick={() => toggle(k)} className="text-gray-400 hover:text-indigo-500 shrink-0"
              aria-label={isOpen ? `Collapse ${line.category_name}` : `Expand ${line.category_name}`}>
              {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
            <span className="truncate font-medium text-gray-900 dark:text-white">{line.category_name}</span>
            {line.rollover_enabled && parseFloat(line.rollover_balance || "0") > 0 && (
              <span className="shrink-0 text-xs px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                +{fmt(parseFloat(line.rollover_balance || "0"))} rolled over
              </span>
            )}
          </div>
          <span className="text-sm tabular-nums text-gray-500 dark:text-gray-400 shrink-0">
            {fmt(spent)}<span className="text-gray-300 dark:text-gray-400"> / {fmt(available)}</span>
          </span>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex-1 h-1.5 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
            <div className={`h-full rounded-full ${barColor(pct)}`} style={{ width: `${Math.min(pct, 100)}%` }} />
          </div>
          <span className={`text-xs tabular-nums shrink-0 ${left < 0 ? "text-red-600 dark:text-red-400" : "text-gray-400"}`}>
            {left < 0 ? `${fmt(Math.abs(left))} over` : `${fmt(left)} left`}
          </span>
        </div>
        {isOpen && <div className="mt-2"><Breakdown categoryId={line.category_id} /></div>}
      </div>
    );
  }

  const status = plan ? leftToAssignStatus(plan.left_to_assign) : null;
  const categoryGroups = (plan?.groups ?? []).filter(g => g.kind !== "uncategorized");
  const uncategorized = (plan?.groups ?? []).find(g => g.kind === "uncategorized");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Budget</h2>
          <button onClick={() => setShowHelp(true)} className="text-gray-300 hover:text-indigo-500" aria-label="Help">
            <HelpCircle size={14} />
          </button>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg bg-gray-100 dark:bg-gray-700 p-1">
            {(["track", "set"] as BudgetTab[]).map(t => (
              <button key={t} type="button"
                onClick={() => setTab(t)}
                className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${tab === t ? "bg-white dark:bg-gray-800 shadow-sm text-gray-900 dark:text-gray-100" : "text-gray-500 dark:text-gray-300"}`}>
                {t === "track" ? "Track Budgets" : "Set Budgets"}
              </button>
            ))}
          </div>
          <MonthYearPicker year={year} month={month} onChange={(y, m) => { setYear(y); setMonth(m); }} />
        </div>
      </div>

      {isLoading && <div className="card text-sm text-gray-400">Loading…</div>}

      {!isLoading && planFailed && !plan && (
        <div role="alert" className="card flex items-center justify-between gap-3 text-sm text-red-600 dark:text-red-400">
          <span>Couldn't load the budget for {monthLabel}.</span>
          <button className="btn-secondary text-xs px-2 py-1" disabled={planFetching} onClick={() => refetchPlan()}>
            {planFetching ? "Retrying…" : "Try again"}
          </button>
        </div>
      )}

      {!isLoading && plan && tab === "track" && (
        <>
          <div className="card bg-gradient-to-br from-indigo-50 to-white dark:from-indigo-950/30 dark:to-transparent">
            <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">{monthLabel}</p>
            <p className={`text-3xl font-bold mt-1 ${totals.left < 0 ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"}`}>
              {totals.left < 0 ? `${fmt(Math.abs(totals.left))} over` : `${fmt(totals.left)} left to spend`}
            </p>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              {fmt(totals.spent)} spent of {fmt(totals.available)} available
              {totals.available !== totals.budgeted && <> ({fmt(totals.budgeted)} budgeted + rollover)</>}
              {overCount(totals.overCount)}
            </p>
            <div className="mt-3 h-2 rounded-full bg-white/70 dark:bg-gray-800 overflow-hidden">
              <div className={`h-full rounded-full ${barColor(totals.pct)}`} style={{ width: `${Math.min(totals.pct, 100)}%` }} />
            </div>
          </div>

          <div className="card">
            <h3 className="font-semibold text-gray-900 dark:text-white mb-1">Budget lines</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
              Each line's budget is its bills from Recurring plus its flexible amount. Expand a line to see what was spent. Switch to Set Budgets to change one.
            </p>
            {lines.length === 0 && (
              <p className="text-sm text-gray-400 py-4 text-center">No budget lines yet. Switch to Set Budgets to add one.</p>
            )}
            {lines.map(l => <React.Fragment key={`${l.category_id}:${l.category_name}`}>{monitorRow(l)}</React.Fragment>)}
          </div>
        </>
      )}

      {!isLoading && plan && status && tab === "set" && (
        <>
          <div className="card space-y-2">
            <div className="flex items-baseline justify-between gap-3 flex-wrap">
              <h3 className="font-semibold text-gray-900 dark:text-white flex items-center gap-1.5">
                Left to assign
                <HowCalculated title="Left to assign" explanations={[plan.explain_left_to_assign]} />
              </h3>
              <span className={cx("text-2xl font-bold tabular-nums",
                status.over ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400")}>
                {fmt(status.amount)} <span className="text-sm font-medium">{status.label}</span>
              </span>
            </div>
            <p className="text-sm tabular-nums text-gray-600 dark:text-gray-300">
              <span title="Recurring income plus planned inflows">Income {fmt(plan.income_total)}</span>
              {" − "}<span title="Bills and planned one-offs this month">Committed {fmt(plan.committed_total)}</span>
              {" − "}<span title="What you've added on top of the bills">Flexible {fmt(plan.flexible_total)}</span>
              {" = "}<span className="font-semibold">{status.over ? "−" : ""}{fmt(status.amount)}</span>
            </p>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Committed comes from <Link to="/recurring" className="underline">Recurring</Link> automatically. Change a bill there and it updates here. Flexible is what you add on top; Budget is the two together.
            </p>
            {plan.unclassified_count > 0 && (
              <Link to="/recurring" className="text-xs text-amber-600 underline">
                {plan.unclassified_count} recurring {plan.unclassified_count === 1 ? "bill has" : "bills have"} no category
              </Link>
            )}
          </div>

          <div className="card">
            <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
              <h3 className="font-semibold text-gray-900 dark:text-white">Budgets</h3>
              <div className="flex items-center gap-2">
                <button onClick={() => applyRolloverMut.mutate()} disabled={applyRolloverMut.isPending}
                  className="btn-secondary text-xs px-2 py-1" title="Carry last month's unspent budget forward">
                  <RotateCcw size={12} /> {applyRolloverMut.isPending ? "Rolling over…" : "Rollover"}
                </button>
                <button onClick={() => setAdding(v => !v)} className="btn-secondary text-xs px-2 py-1">
                  <Plus size={12} /> Add
                </button>
              </div>
            </div>
            <p className="mb-2 text-right text-xs text-gray-400">Rollover uses your Flexible amount only, not bills.</p>

            {adding && (
              <div className="flex flex-wrap items-center gap-2 mb-3 bg-gray-50 dark:bg-gray-800/50 rounded-md px-3 py-2">
                <select className="input py-1 text-sm" value={addCat} onChange={e => setAddCat(e.target.value)}>
                  <option value="">Choose a category…</option>
                  <CategoryOptions categories={categories as any[]} type="expense" exclude={shownIds} />
                </select>
                <input type="number" step="0.01" min="0" className="input w-28 py-1 text-sm text-right"
                  placeholder="Flexible" value={addAmt} onChange={e => setAddAmt(e.target.value)} />
                {addCat && monthOnly(Number(addCat)) && <span className="text-xs text-gray-400">for {monthLabel} only</span>}
                <button className="btn-primary text-xs px-2 py-1" disabled={!addCat || !addAmt || upsertMut.isPending}
                  onClick={() => save(Number(addCat), addAmt, "add")}>
                  {upsertMut.isPending && savingKey === "add" ? "Saving…" : "Add"}
                </button>
                <button className="text-xs text-gray-400 hover:text-gray-600" disabled={upsertMut.isPending && savingKey === "add"}
                  onClick={() => setAdding(false)}>Cancel</button>
                {upsertMut.isError && savingKey === "add" && (
                  <span role="alert" className="text-xs text-red-500">Save failed — try again</span>
                )}
              </div>
            )}

            <div className={cx("hidden sm:grid", COLS, "pb-1 text-xs font-medium text-gray-400")}>
              <span>Category</span>
              <span className="text-right">Committed</span>
              <span className="text-right">Flexible</span>
              <span className="text-right">Budget</span>
            </div>
            {categoryGroups.length === 0 && (
              <p className="text-sm text-gray-400 py-4 text-center">
                No bills or budgets yet. Add a flexible amount, or start from what you already spend below.
              </p>
            )}
            {categoryGroups.map(g => <React.Fragment key={`${g.kind}:${g.group_id ?? g.group_name}`}>{groupView(g)}</React.Fragment>)}
            {categoryGroups.length > 0 && (
              line4(
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Budget across categories</span>,
                <span className="text-sm tabular-nums text-gray-500">
                  {fmt(categoryGroups.reduce((s, g) => s + parseFloat(g.committed), 0))}
                </span>,
                <span className="text-sm tabular-nums text-gray-500">
                  {fmt(categoryGroups.reduce((s, g) => s + parseFloat(g.flexible), 0))}
                </span>,
                <span className="text-sm font-semibold tabular-nums text-gray-900 dark:text-white">{fmt(plan.category_budget_total)}</span>,
                "pt-2 mt-2 border-t border-gray-200 dark:border-gray-700",
              )
            )}
            {uncategorized && (
              <>
                {groupView(uncategorized)}
                <p className="pl-3 mt-1 text-xs text-gray-400">
                  Counted in Committed above, but not in any category, so Track Budgets can't measure it. Give these a category on Recurring.
                </p>
              </>
            )}
          </div>

          {unbudgeted.length > 0 && (
            <div className="card">
              <h3 className="font-semibold text-gray-900 dark:text-white">Spending with no budget</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
                What you spent here this month. Add it as a flexible amount in one click, then adjust.
              </p>
              <div className="space-y-2">
                {unbudgeted.map(r => (
                  <div key={r.category_id} className="flex items-center justify-between gap-3">
                    <span className="text-sm text-gray-700 dark:text-gray-300 truncate">
                      {r.category_name}
                      {monthOnly(r.category_id) && <span className="ml-2 text-xs text-gray-400">for {monthLabel} only</span>}
                    </span>
                    <div className="flex flex-wrap items-center justify-end gap-2 shrink-0">
                      <span className="text-sm tabular-nums text-gray-500 dark:text-gray-400">{fmt(parseFloat(r.actual_total))}</span>
                      <button className="btn-secondary text-xs px-2 py-0.5" disabled={upsertMut.isPending}
                        onClick={() => save(r.category_id, r.actual_total, `unb:${r.category_id}`)}>
                        {upsertMut.isPending && savingKey === `unb:${r.category_id}` ? "Saving…" : "Budget this"}
                      </button>
                      {upsertMut.isError && savingKey === `unb:${r.category_id}` && (
                        <span role="alert" className="text-xs text-red-500">Save failed — try again</span>
                      )}
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
            "Set Budgets is one list. Each category shows Committed, Flexible and Budget. Committed is the bills and planned one-offs that land this month, read from Recurring automatically; you never type it. Flexible is what you add on top (groceries, shopping, a cushion). Budget is the two together.\n\n" +
            "The header reads Income − Committed − Flexible = Left to assign. Income and Committed are the same numbers the Recurring tab shows, so Income − Committed is Recurring's 'Left over'. Green means money is still unassigned; red means you've assigned more than comes in.\n\n" +
            "A budget set on a parent category (for example a group like Necessities) is treated as that group's total: the bills and flexible amounts under it count inside it, never on top of it. Whatever it doesn't cover yet shows as 'Rest of …'. Remove it and the group simply adds up its rows.\n\n" +
            "Track Budgets measures each line's Budget against what you actually spent. Its budgeted total always equals 'Budget across categories' on Set Budgets; 'available' adds any rolled-over balance on top. Rollover uses your Flexible amount only, not bills.\n\n" +
            "Flexible amounts are saved as 'every month' by default. The exception is an assignable bucket while carry-forward is off (Settings → Preferences): those are set for the month you're viewing only."
          }
          onClose={() => setShowHelp(false)}
        />
      )}
    </div>
  );
}

function overCount(n: number): React.ReactNode {
  return n > 0 ? <span className="text-red-500"> · {n} over budget</span> : null;
}

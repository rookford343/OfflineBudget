import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { budgetApi } from "../api";
import { fmt, cx } from "../lib/utils";
import { ChevronDown, ChevronRight } from "lucide-react";

/**
 * Zero-based view of the month. Committed lines come from recurring bills
 * (plus Savings and Groceries) and are read-only here; the rest of the
 * leftover is assigned to a few buckets until "unassigned" reaches $0.
 */
export default function LeftToBudgetPanel({ year, month }: { year: number; month: number }) {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["left-to-budget", year, month],
    queryFn: () => budgetApi.leftToBudget(year, month),
  });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [drafts, setDrafts] = useState<Record<number, string>>({});

  // Budget.tsx mounts this component with key={`${year}-${month}`}, so a
  // month switch always gets a fresh instance -- new drafts, new mutation,
  // new isPending/isError state. No in-component reset needed, and (more
  // importantly) no risk of a prior month's in-flight/failed save bleeding
  // into the newly viewed month's UI.
  const save = useMutation({
    mutationFn: ({ category_id, amount, year: y, month: m }: { category_id: number; amount: string; year: number; month: number }) =>
      budgetApi.upsert({ category_id, year: y, month: m, budgeted_amount: amount }),
    onSuccess: (_data, variables) => {
      // Drop the draft so the input falls back to the freshly-fetched
      // (now-authoritative) value instead of continuing to show what was typed.
      setDrafts((d) => {
        const next = { ...d };
        delete next[variables.category_id];
        return next;
      });
      // Invalidate the month the save was actually issued for (from
      // variables), not whatever year/month happens to be in this closure --
      // matters if props changed while the request was in flight.
      qc.invalidateQueries({ queryKey: ["left-to-budget", variables.year, variables.month] });
      // Budget.tsx's own allocation queries -- not "budget"-prefixed.
      qc.invalidateQueries({ queryKey: ["budget-overview"] });
      qc.invalidateQueries({ queryKey: ["budget-allocations"] });
    },
  });

  if (!data) return null;
  const unassigned = Number(data.unassigned);
  const tone = unassigned === 0 ? "text-emerald-600" : unassigned > 0 ? "text-amber-600" : "text-red-600";
  const barTone = unassigned === 0 ? "bg-emerald-500" : unassigned > 0 ? "bg-amber-500" : "bg-red-500";
  const leftover = Number(data.leftover);
  const pct = leftover > 0 ? Math.min(100, (Number(data.assigned_total) / leftover) * 100) : 100;

  const toggle = (k: string) =>
    setExpanded((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; });

  return (
    <div className="card space-y-4">
      <div>
        <div className="flex items-baseline justify-between">
          <h2 className="font-semibold">Left to budget</h2>
          <span className={cx("text-lg font-semibold", tone)}>
            {fmt(data.unassigned)} {unassigned < 0 ? "over-assigned" : "unassigned"}
          </span>
        </div>
        <p className="text-xs text-gray-400">
          {fmt(data.leftover)} left after committed · {fmt(data.assigned_total)} assigned
        </p>
        <div className="mt-2 h-2 w-full rounded bg-gray-100 dark:bg-gray-700">
          <div className={cx("h-2 rounded", barTone)} style={{ width: `${pct}%` }} />
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Committed</h3>
          {data.committed.map((r: any) => {
            const k = `${r.category_id ?? "none"}:${r.category_name}`;
            const isOpen = expanded.has(k);
            return (
              <div key={k} className="py-1">
                <button
                  type="button"
                  className="flex w-full items-center justify-between text-sm"
                  onClick={() => r.items.length && toggle(k)}
                  aria-label={r.items.length ? (isOpen ? `Collapse ${r.category_name}` : `Expand ${r.category_name}`) : undefined}
                >
                  <span className="flex items-center gap-1">
                    {r.items.length > 0 && (isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />)}
                    {r.category_name === "Unclassified"
                      ? <Link to="/recurring" className="text-amber-600 underline">Unclassified</Link>
                      : r.category_name}
                  </span>
                  <span>{fmt(r.amount)}</span>
                </button>
                {isOpen && r.items.map((b: any) => (
                  <div key={b.recurring_item_id} className="flex justify-between pl-5 text-xs text-gray-500">
                    <span>{b.name}</span><span>{fmt(b.amount)}</span>
                  </div>
                ))}
              </div>
            );
          })}
        </div>

        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">Assign</h3>
          {data.assignable.map((a: any) => {
            // One mutation instance handles every row in this month (fresh
            // per month via Budget.tsx's key={`${year}-${month}`}); `variables`
            // says which category_id the in-flight (or last-failed) call was
            // for, so pending/error state can be shown per row instead of
            // for the whole panel.
            const isThisRow = save.variables?.category_id === a.category_id;
            const isSaving = save.isPending && isThisRow;
            const failed = save.isError && isThisRow;
            return (
              <div key={a.category_id} className="py-1">
                <div className="flex items-center justify-between gap-2 text-sm">
                  <span>
                    {a.category_name}
                    {!a.is_set && <span className="ml-2 text-xs text-gray-400">not assigned yet</span>}
                  </span>
                  <input
                    type="number" step="0.01" min="0"
                    aria-label={`Assign amount for ${a.category_name}`}
                    className="input w-28 text-right text-sm"
                    value={drafts[a.category_id] ?? (a.is_set ? a.assigned : "")}
                    placeholder="0.00"
                    disabled={isSaving}
                    onChange={(e) => setDrafts((d) => ({ ...d, [a.category_id]: e.target.value }))}
                    onBlur={(e) => {
                      const v = e.target.value;
                      if (v !== "" && v !== String(a.assigned)) save.mutate({ category_id: a.category_id, amount: v, year, month });
                    }}
                  />
                </div>
                {/* Keep the typed draft visible on failure (it's not cleared
                    here, only on success above) so the user can retry without
                    retyping. */}
                {failed && (
                  <p className="text-right text-xs text-red-500">Save failed — try again</p>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

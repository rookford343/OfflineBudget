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

  const save = useMutation({
    mutationFn: ({ category_id, amount }: { category_id: number; amount: string }) =>
      budgetApi.upsert({ category_id, year, month, budgeted_amount: amount }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["left-to-budget", year, month] });
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
          {data.assignable.map((a: any) => (
            <div key={a.category_id} className="flex items-center justify-between gap-2 py-1 text-sm">
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
                onChange={(e) => setDrafts((d) => ({ ...d, [a.category_id]: e.target.value }))}
                onBlur={(e) => {
                  const v = e.target.value;
                  if (v !== "" && v !== String(a.assigned)) save.mutate({ category_id: a.category_id, amount: v });
                }}
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

import { useState } from "react";
import { ChevronDown, ChevronRight, Landmark } from "lucide-react";
import { fmt } from "../lib/utils";

/**
 * "By account" rollup for the Recurring page: account/card -> category -> bill,
 * each level collapsed by default and sorted largest-monthly-first. Backend
 * already sorts every level (backend/routers/recurring.py get_breakdown) --
 * this component just renders what it's given, same shape as
 * RecurringCategoryRollup.
 *
 * Note: unlike by_category/by_owner, by_account has no synthetic catch-all
 * bucket, but group_id is NOT globally unique here -- an Account row and a
 * CreditCard row can share the same numeric id for the same user (separate
 * autoincrement sequences on separate tables). groupKey below combines
 * group_id with group_name so a collision can't produce a duplicate React
 * key or cross-wire two groups' expand/collapse state.
 */
export default function RecurringAccountRollup({ groups }: { groups: any[] }) {
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());
  const [openCats, setOpenCats] = useState<Set<string>>(new Set());

  if (!groups || groups.length === 0) return null;

  const toggleGroup = (key: string) =>
    setOpenGroups((s) => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n; });
  const toggleCat = (key: string) =>
    setOpenCats((s) => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n; });

  return (
    <div className="card">
      <h3 className="mb-3 flex items-center gap-2 font-semibold text-gray-900 dark:text-white">
        <Landmark size={16} className="text-indigo-500" /> By Account
      </h3>
      <div className="space-y-1">
        {groups.map((g) => {
          const groupKey = `${g.group_id ?? "unclassified"}:${g.group_name}`;
          const isOpen = openGroups.has(groupKey);
          const isUnclassified = g.group_id === null;
          return (
            <div key={groupKey} className="border-b border-gray-50 py-1 last:border-0 dark:border-gray-800">
              <button
                type="button"
                onClick={() => toggleGroup(groupKey)}
                aria-expanded={isOpen}
                aria-label={`${isOpen ? "Collapse" : "Expand"} ${g.group_name}`}
                className="flex w-full items-center justify-between gap-2 text-sm font-medium"
              >
                <span className="flex items-center gap-1 text-gray-900 dark:text-white">
                  {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  {g.group_name}
                  {isUnclassified && (
                    <span className="text-xs font-normal text-amber-600 dark:text-amber-400">
                      (assign categories via the Needs-a-home inbox above)
                    </span>
                  )}
                </span>
                <span className="tabular-nums text-gray-700 dark:text-gray-300">{fmt(g.monthly)} avg/mo</span>
              </button>

              {isOpen && (
                <div className="mt-1 space-y-1 pl-5">
                  {g.categories.map((c: any) => {
                    const catKey = `${groupKey}:${c.category_id}`;
                    const catOpen = openCats.has(catKey);
                    return (
                      <div key={catKey}>
                        <button
                          type="button"
                          onClick={() => toggleCat(catKey)}
                          aria-expanded={catOpen}
                          aria-label={`${catOpen ? "Collapse" : "Expand"} ${c.category_name}`}
                          className="flex w-full items-center justify-between gap-2 text-sm"
                        >
                          <span className="flex items-center gap-1 text-gray-700 dark:text-gray-300">
                            {catOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                            {c.category_name}
                          </span>
                          <span className="tabular-nums text-gray-600 dark:text-gray-400">{fmt(c.monthly)} avg/mo</span>
                        </button>
                        {catOpen && (
                          <div className="space-y-0.5 pl-5">
                            {c.items.map((item: any) => (
                              <div key={item.id} className="flex items-center justify-between gap-2 text-xs text-gray-500 dark:text-gray-400">
                                <span className="truncate">{item.name}</span>
                                <span className="shrink-0 tabular-nums">{fmt(item.monthly_equivalent)} avg/mo</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                  {g.items.map((item: any) => (
                    <div key={item.id} className="flex items-center justify-between gap-2 text-xs text-gray-500 dark:text-gray-400">
                      <span className="truncate">{item.name}</span>
                      <span className="shrink-0 tabular-nums">{fmt(item.monthly_equivalent)} avg/mo</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

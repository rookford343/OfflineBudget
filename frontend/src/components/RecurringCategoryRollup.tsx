import { useState } from "react";
import { ChevronDown, ChevronRight, ListTree } from "lucide-react";
import { fmt } from "../lib/utils";

/**
 * "By category" rollup for the Recurring page: group -> category -> bill,
 * each level collapsed by default and sorted largest-monthly-first. Backend
 * already sorts every level (backend/routers/recurring.py get_breakdown) and
 * always puts the synthetic "Unclassified" group last -- this component just
 * renders what it's given.
 */
export default function RecurringCategoryRollup({ groups }: { groups: any[] }) {
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
        <ListTree size={16} className="text-indigo-500" /> By Category
      </h3>
      <div className="space-y-1">
        {groups.map((g) => {
          const groupKey = String(g.group_id ?? "unclassified");
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

import { useState } from "react";
import { ChevronDown, ChevronRight, Users } from "lucide-react";
import { fmt } from "../lib/utils";

/**
 * "By owner" rollup for the Recurring page: owner -> bill, one level deep
 * (no nested category layer -- this is a second, independent axis on the
 * same items, not a merge with the category rollup). Each owner collapsed by
 * default. Backend already sorts by monthly descending with the Family
 * bucket trailing (backend/routers/recurring.py get_breakdown) -- this
 * component just renders what it's given, same as RecurringCategoryRollup.
 */
export default function RecurringOwnerRollup({ groups }: { groups: any[] }) {
  const [openOwners, setOpenOwners] = useState<Set<string>>(new Set());

  if (!groups || groups.length === 0) return null;

  const toggleOwner = (key: string) =>
    setOpenOwners((s) => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n; });

  return (
    <div className="card">
      <h3 className="mb-3 flex items-center gap-2 font-semibold text-gray-900 dark:text-white">
        <Users size={16} className="text-indigo-500" /> By Owner
      </h3>
      <div className="space-y-1">
        {groups.map((g) => {
          const ownerKey = String(g.owner_id ?? "family");
          const isOpen = openOwners.has(ownerKey);
          return (
            <div key={ownerKey} className="border-b border-gray-50 py-1 last:border-0 dark:border-gray-800">
              <button
                type="button"
                onClick={() => toggleOwner(ownerKey)}
                aria-expanded={isOpen}
                aria-label={`${isOpen ? "Collapse" : "Expand"} ${g.owner_name}`}
                className="flex w-full items-center justify-between gap-2 text-sm font-medium"
              >
                <span className="flex items-center gap-1 text-gray-900 dark:text-white">
                  {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  {g.owner_name}
                </span>
                <span className="tabular-nums text-gray-700 dark:text-gray-300">{fmt(g.monthly)} avg/mo</span>
              </button>

              {isOpen && (
                <div className="mt-1 space-y-0.5 pl-5">
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
